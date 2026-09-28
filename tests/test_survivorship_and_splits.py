"""Tests for survivorship bias point-in-time correctness, corporate action split handling,
real cumulative VWAP, and dual table storage.
"""

from __future__ import annotations

import asyncio
from datetime import date, datetime
from unittest.mock import AsyncMock, patch

import numpy as np
import polars as pl
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from nexus_astra.backtesting.survivorship_bias import SurvivorshipCorrector
from nexus_astra.data_ingestion import (
    CorporateActions,
    DailyPriceData,
    DatabaseManager,
    MarketDataFetcher,
    PricesRaw,
    SocialScraper,
)
from nexus_astra.data_ingestion.database import IndexConstituents
from nexus_astra.feature_engineering import AlphaFeatures
from scripts.populate_constituents import populate_index_constituents


@pytest.fixture
def in_memory_db():
    """Create an isolated in-memory SQLite database manager."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)

    class CustomDbManager:
        def __init__(self):
            self.engine = engine
            self.SessionLocal = SessionLocal

        def create_tables(self):
            PricesRaw.metadata.create_all(bind=self.engine)

        def session_scope(self):
            from contextlib import contextmanager
            @contextmanager
            def scope():
                session = SessionLocal()
                try:
                    yield session
                    session.commit()
                except Exception:
                    session.rollback()
                    raise
                finally:
                    session.close()
            return scope()

    mgr = CustomDbManager()
    mgr.create_tables()
    return mgr


def test_index_constituents_population_and_count():
    """Verify that IndexConstituents table is populated with historical changes and count > 0."""
    from nexus_astra.data_ingestion.database import database_manager
    with database_manager.session_scope() as session:
        count = session.query(IndexConstituents).count()
        assert count > 0, "IndexConstituents table should not be empty after population"
        assert count >= 50, f"Expected at least 50 constituents, found {count}"


def test_point_in_time_constituents_2020_vs_2026():
    """Verify that a backtest on 2020-01-15 uses point-in-time constituents as of 2020-01-15,
    NOT 2026 constituents (e.g. JIOFIN, TRENT, BEL were not in Nifty 50 in 2020).
    """
    corrector = SurvivorshipCorrector()

    # Query point-in-time universe for 2020-01-15
    constituents_2020 = corrector.point_in_time_filter(date(2020, 1, 15), index_name="NIFTY_50")
    assert len(constituents_2020) > 0, "2020 PIT universe should not be empty"

    # In 2020, YESBANK, VEDL, ZEEL, INFRATEL, IOC, GAIL, HDFC were active constituents
    assert "YESBANK" in constituents_2020, "YESBANK must be present on 2020-01-15"
    assert "VEDL" in constituents_2020, "VEDL must be present on 2020-01-15"
    assert "ZEEL" in constituents_2020, "ZEEL must be present on 2020-01-15"
    assert "INFRATEL" in constituents_2020, "INFRATEL must be present on 2020-01-15"
    assert "HDFC" in constituents_2020, "HDFC must be present on 2020-01-15"
    assert "IOC" in constituents_2020, "IOC must be present on 2020-01-15"

    # Future additions (post-2020) MUST NOT be present in 2020
    assert "JIOFIN" not in constituents_2020, "JIOFIN (2025/2023) must NOT be in 2020 universe (survivorship bias!)"
    assert "TRENT" not in constituents_2020, "TRENT (2024) must NOT be in 2020 universe"
    assert "BEL" not in constituents_2020, "BEL (2024) must NOT be in 2020 universe"
    assert "SHRIRAMFIN" not in constituents_2020, "SHRIRAMFIN (2024) must NOT be in 2020 universe"
    assert "ADANIENT" not in constituents_2020, "ADANIENT (2022) must NOT be in 2020 universe"
    assert "APOLLOHOSP" not in constituents_2020, "APOLLOHOSP (2022) must NOT be in 2020 universe"

    # Query point-in-time universe for 2026-01-15
    constituents_2026 = corrector.point_in_time_filter(date(2026, 1, 15), index_name="NIFTY_50")
    assert "JIOFIN" in constituents_2026
    assert "TRENT" in constituents_2026
    assert "BEL" in constituents_2026
    assert "SHRIRAMFIN" in constituents_2026
    assert "ADANIENT" in constituents_2026

    # Excluded stocks must NOT be in 2026 universe
    assert "YESBANK" not in constituents_2026
    assert "VEDL" not in constituents_2026
    assert "ZEEL" not in constituents_2026
    assert "HDFC" not in constituents_2026


def test_reliance_split_no_false_short_signal():
    """Verify that a 2:1 stock split (e.g. Reliance nominal price drops from 2800 to 1400)
    uses Adj Close for returns, producing ~0% return and preventing a false short signal.
    """
    # 5 days of data around a 2:1 split
    # Day 3 is split day: nominal price drops 2800 -> 1400 (-50%), but adj_close is continuous
    raw_frame = pl.DataFrame(
        {
            "date": ["2024-10-25", "2024-10-26", "2024-10-27", "2024-10-28", "2024-10-29"],
            "open": [2790.0, 2795.0, 1395.0, 1405.0, 1410.0],
            "high": [2820.0, 2810.0, 1420.0, 1425.0, 1430.0],
            "low": [2780.0, 2785.0, 1390.0, 1395.0, 1400.0],
            "close": [2800.0, 2800.0, 1400.0, 1410.0, 1420.0],  # 2:1 split on 2024-10-27
            "adj_close": [1400.0, 1400.0, 1400.0, 1410.0, 1420.0],  # Corporate action adjusted
            "volume": [1000000, 1200000, 2500000, 2200000, 2100000],
        }
    )

    alpha_engine = AlphaFeatures(raw_frame)
    features = alpha_engine.compute()

    log_returns = features.get_column("log_return").to_list()

    # Day 3 return (index 2):
    # Without Adj Close, nominal close went 2800 -> 1400 => log(1400/2800) = -0.693 (-50% crash)
    # With Adj Close, adj_close went 1400 -> 1400 => log(1400/1400) = 0.0
    split_day_return = log_returns[2]
    assert split_day_return is not None
    assert abs(split_day_return) < 0.001, f"Expected ~0 return on split date, got {split_day_return}"
    assert split_day_return > -0.10, "Split must NOT trigger a false -50% crash or short signal!"


def test_survivorship_delisted_penalty_actual_return():
    """Verify that delisted stocks receive actual delisted return (-100% loss)
    rather than a flat 15% heuristic penalty.
    """
    corrector = SurvivorshipCorrector()

    # DHFL was delisted in June 2021
    # When trading/holding through or after delisting date:
    trade_date = date(2021, 6, 20)
    raw_return = 0.05  # Strategy thought it made +5%

    adjusted = corrector.apply_delisted_penalty(signal_date=trade_date, symbol="DHFL", raw_return=raw_return)
    assert isinstance(adjusted, float)
    # Actual delisted return is -100% (-1.0)
    assert adjusted == -1.0, f"Expected actual delisted return -1.0 (-100%), got {adjusted}"

    # With 20% recovery
    adjusted_with_recovery = corrector.apply_delisted_penalty(
        signal_date=trade_date, symbol="DHFL", raw_return=raw_return, recovery_pct=0.20
    )
    assert round(adjusted_with_recovery, 2) == -0.80  # -100% + 20% recovery = -80%


def test_empty_constituents_returns_data_fail(in_memory_db):
    """Verify that if IndexConstituents table is empty, apply_delisted_penalty returns DATA_FAIL."""
    corrector = SurvivorshipCorrector()
    # Mock database_manager to point to empty in-memory DB
    with patch("nexus_astra.backtesting.survivorship_bias.database_manager", in_memory_db):
        corrector._constituents_cache = None
        result = corrector.apply_delisted_penalty(
            signal_date=date(2026, 1, 1),
            symbol="RELIANCE",
            raw_return=0.05,
        )
        assert result == "DATA_FAIL", f"Expected 'DATA_FAIL' on empty constituents table, got {result}"


def test_data_fetcher_dual_table_storage_and_real_vwap(in_memory_db):
    """Verify that MarketDataFetcher stores to prices_raw, corporate_actions, and calculates real cumulative VWAP."""
    import pandas as pd

    # Mock yfinance return with Adj Close, Dividends, Stock Splits
    mock_df = pd.DataFrame(
        {
            "Open": [100.0, 105.0, 110.0],
            "High": [105.0, 110.0, 115.0],
            "Low": [95.0, 100.0, 105.0],
            "Close": [102.0, 108.0, 112.0],
            "Adj Close": [51.0, 54.0, 112.0],  # Prior 2:1 split adjusted
            "Volume": [1000, 2000, 3000],
            "Dividends": [0.0, 2.50, 0.0],     # Dividend on Day 2
            "Stock Splits": [0.0, 0.0, 2.0],   # 2:1 split on Day 3
        },
        index=pd.to_datetime(["2026-06-10", "2026-06-11", "2026-06-12"]),
    )
    mock_df.index.name = "Date"

    fetcher = MarketDataFetcher(db_manager=in_memory_db)
    polars_frame = fetcher._to_polars(mock_df, "RELIANCE")

    # 1. Verify columns kept
    assert "adj_close" in polars_frame.columns
    assert "dividends" in polars_frame.columns
    assert "stock_splits" in polars_frame.columns
    assert "vwap" in polars_frame.columns

    # 2. Verify real cumulative VWAP:
    # Day 1: typical price = (105 + 95 + 102)/3 = 100.6667
    # PV1 = 100.6667 * 1000 = 100666.67, CumVol = 1000 => VWAP1 = 100.6667
    # Day 2: typical price = (110 + 100 + 108)/3 = 106.0
    # PV2 = 106.0 * 2000 = 212000, CumPV = 312666.67, CumVol = 3000 => VWAP2 = 312666.67 / 3000 = 104.222
    vwaps = polars_frame.get_column("vwap").to_list()
    assert abs(vwaps[0] - 100.6667) < 0.01
    assert abs(vwaps[1] - 104.2222) < 0.01

    # 3. Persist and check tables
    from nexus_astra.data_ingestion.data_fetcher import FetchResult
    results = [FetchResult(symbol="RELIANCE", frame=polars_frame)]
    fetcher._persist_daily_price_data(results)

    with in_memory_db.session_scope() as session:
        # Check prices_raw
        raw_rows = session.query(PricesRaw).filter(PricesRaw.symbol == "RELIANCE").all()
        assert len(raw_rows) == 3
        assert float(raw_rows[0].adj_close) == 51.0

        # Check daily_price_data
        daily_rows = session.query(DailyPriceData).filter(DailyPriceData.symbol == "RELIANCE").all()
        assert len(daily_rows) == 3
        assert float(daily_rows[0].adj_close) == 51.0

        # Check corporate_actions
        corp_rows = session.query(CorporateActions).filter(CorporateActions.symbol == "RELIANCE").all()
        assert len(corp_rows) == 2  # 1 dividend + 1 split
        action_types = {r.action_type for r in corp_rows}
        assert "DIVIDEND" in action_types
        assert "SPLIT" in action_types


def test_social_fetcher_point_in_time_universe():
    """Verify that SocialScraper dynamically uses the point-in-time universe as of the target date."""
    scraper_2020 = SocialScraper(as_of_date=date(2020, 1, 15))
    # In 2020, JIOFIN should NOT be in assets
    assert "JIOFIN" not in scraper_2020.assets
    assert "YESBANK" in scraper_2020.assets

    # In 2026, JIOFIN should be in assets
    scraper_2026 = SocialScraper(as_of_date=date(2026, 1, 15))
    assert "JIOFIN" in scraper_2026.assets
    assert "YESBANK" not in scraper_2026.assets

    # Explicit universe override
    custom_scraper = SocialScraper(universe=["TCS", "INFY"])
    assert "TCS" in custom_scraper.assets
    assert "INFY" in custom_scraper.assets
    assert "RELIANCE" not in custom_scraper.assets
