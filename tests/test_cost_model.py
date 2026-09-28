"""Unit and integration tests for IndiaCostModel, WalkForwardBacktester cost integration,
and PaperTrader cost/slippage deduction.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Generator
import numpy as np
import polars as pl
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from nexus_astra.backtesting.cost_model import CostBreakdown, IndiaCostModel, cost_model
from nexus_astra.backtesting.paper_trader import PaperTrader
from nexus_astra.backtesting.walkforward_engine import WalkForwardBacktester
from nexus_astra.data_ingestion.database import (
    Base,
    DailyPriceData,
    TheoreticalTrades,
    PricesRaw,
)


@pytest.fixture
def test_db_manager():
    """Create an isolated in-memory SQLite database manager for testing."""
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
            Base.metadata.create_all(bind=self.engine)

        def session_scope(self) -> Generator[Session, None, None]:
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


# ==============================================================================
# 1. 1 LAKH DELIVERY TRADE COST SPECIFICATION (200 - 350 RANGE)
# ==============================================================================

def test_round_trip_cost_1l_in_range():
    """Verify that a 1 Lakh (₹100,000) round-trip delivery equity trade costs 200 - 350 INR."""
    model = IndiaCostModel()

    # Using helper property
    cost_1l = model.round_trip_cost_1l(instrument="DELIVERY", symbol="RELIANCE")
    assert 200.0 <= cost_1l <= 350.0, f"Expected 1L round trip cost in [200, 350], got {cost_1l:.2f}"

    # Using calculate_round_trip_cost directly
    breakdown = model.calculate_round_trip_cost(value=100000.0, instrument="DELIVERY", symbol="RELIANCE")
    assert 200.0 <= breakdown.total_statutory_and_brokerage <= 350.0
    assert 200.0 <= breakdown <= 350.0  # Dunder comparison check

    # Exact breakdown verification for ₹100,000 buy and ₹100,000 sell:
    # STT: 100 buy + 100 sell = 200
    # Stamp: 15 buy + 0 sell = 15
    # Exch: 3.25 buy + 3.25 sell = 6.50
    # SEBI: 0.10 buy + 0.10 sell = 0.20
    # Brokerage: 20 buy + 20 sell = 40 (capped at 20 each)
    # GST: 18% on (40 + 6.50 + 0.20) = 8.406
    # Total = 200 + 15 + 6.50 + 0.20 + 40 + 8.406 = 270.106 ≈ 270.11 INR
    assert round(breakdown.stt_buy + breakdown.stt_sell, 2) == 200.00
    assert round(breakdown.stamp_duty_buy, 2) == 15.00
    assert round(breakdown.exchange_charges, 2) == 6.50
    assert round(breakdown.sebi_charges, 2) == 0.20
    assert round(breakdown.brokerage_buy + breakdown.brokerage_sell, 2) == 40.00
    assert round(breakdown.total_statutory_and_brokerage, 2) == 270.11


# ==============================================================================
# 2. COST > 0 FOR EVERY TRADE (DELIVERY, FUTURES, OPTIONS)
# ==============================================================================

@pytest.mark.parametrize("instrument", ["DELIVERY", "FUTURES", "OPTIONS"])
@pytest.mark.parametrize("value", [1000.0, 10000.0, 50000.0, 100000.0, 500000.0, 1000000.0])
def test_cost_greater_than_zero_for_all_instruments(instrument: str, value: float):
    """Unit test: cost must be strictly greater than zero for every trade across all instruments and trade sizes."""
    model = IndiaCostModel()

    if instrument == "DELIVERY":
        breakdown = model.calculate_delivery_cost(entry_price=value, exit_price=value * 1.02, quantity=1)
    elif instrument == "FUTURES":
        breakdown = model.calculate_futures_cost(entry_price=value, exit_price=value * 1.02, quantity=1)
    else:
        breakdown = model.calculate_options_cost(entry_price=value, exit_price=value * 1.02, quantity=1)

    assert breakdown.total_statutory_and_brokerage > 0.0, f"Statutory cost should be > 0 for {instrument} at {value}"
    assert breakdown.total_cost_inr > 0.0
    assert breakdown.cost_fraction > 0.0
    assert breakdown.brokerage_buy > 0.0
    assert breakdown.brokerage_sell > 0.0
    assert breakdown.exchange_charges > 0.0
    assert breakdown.sebi_charges > 0.0
    assert breakdown.gst > 0.0


def test_options_exercised_vs_unexercised_stt():
    """Verify Options STT charges under both exercised (on intrinsic) and unexercised (on premium) scenarios."""
    model = IndiaCostModel()

    # Unexercised (squared off): STT = 0.0625% on sell premium
    breakdown_sq = model.calculate_options_cost(
        entry_price=100.0, exit_price=150.0, quantity=100, is_exercised=False
    )
    expected_stt_sell_sq = (150.0 * 100) * 0.000625
    assert abs(breakdown_sq.stt_sell - expected_stt_sell_sq) < 1e-4

    # Exercised: STT = 0.125% on intrinsic value
    breakdown_ex = model.calculate_options_cost(
        entry_price=100.0, exit_price=150.0, quantity=100, is_exercised=True, intrinsic_value=50.0
    )
    expected_stt_sell_ex = (50.0 * 100) * 0.00125
    assert abs(breakdown_ex.stt_sell - expected_stt_sell_ex) < 1e-4
    assert breakdown_ex.total_statutory_and_brokerage > 0


# ==============================================================================
# 3. SLIPPAGE MODEL (LARGE-CAP VS MID/SMALL-CAP & DYNAMIC ESTIMATION)
# ==============================================================================

def test_slippage_tiering():
    """Large-cap should receive 10 bps slippage, mid/small-cap 30 bps fallback."""
    model = IndiaCostModel()

    # Large caps: 10 bps = 0.0010
    assert model.get_slippage_rate("RELIANCE") == 0.0010
    assert model.get_slippage_rate("TCS") == 0.0010
    assert model.get_slippage_rate("HDFCBANK") == 0.0010
    assert model.get_slippage_rate("NIFTY") == 0.0010

    # Mid/Small caps: 30 bps = 0.0030
    assert model.get_slippage_rate("SMALLCAP_XYZ") == 0.0030
    assert model.get_slippage_rate("UNLISTED_TICKER") == 0.0030


def test_dynamic_slippage_from_database(test_db_manager):
    """Dynamic slippage should calibrate against 30-day median spreads if price data is available."""
    model = IndiaCostModel(db_manager=test_db_manager)

    # Insert 30 days of price data with high-low spread of ~4%
    symbol = "TESTSTOCK"
    with test_db_manager.session_scope() as session:
        base_date = date.today()
        for i in range(30):
            d = base_date - timedelta(days=i)
            # High = 102, Low = 98, Close = 100 -> Spread = (102 - 98) / 100 = 0.04 (4%)
            # Effective slippage = median spread * 0.05 = 0.04 * 0.05 = 0.0020 (20 bps)
            row = PricesRaw(
                symbol=symbol,
                trade_date=d,
                open=100.0,
                high=102.0,
                low=98.0,
                close=100.0,
                adj_close=100.0,
                volume=10000,
            )
            session.add(row)

    dyn_slippage = model.get_slippage_rate(symbol)
    assert 0.0018 <= dyn_slippage <= 0.0022, f"Expected dynamic slippage around 0.0020, got {dyn_slippage}"


# ==============================================================================
# 4. BACKTEST SHARPE DROPS VS ZERO-COST VERSION (REALISM PROVEN)
# ==============================================================================

def test_walkforward_backtest_sharpe_drops_with_costs():
    """Verify that including realistic Indian market costs strictly reduces Sharpe and expectancy vs zero-cost."""
    # Create 100 days of synthetic trending data with long signals
    n_days = 100
    dates = [date(2023, 1, 1) + timedelta(days=i) for i in range(n_days)]

    # Price starts at 100 and has modest positive drift with volatility
    np.random.seed(42)
    prices = [100.0]
    for _ in range(n_days - 1):
        ret = np.random.normal(0.002, 0.01)  # positive drift
        prices.append(prices[-1] * (1 + ret))

    prices = np.array(prices)
    highs = prices * 1.01
    lows = prices * 0.99
    opens = prices * 0.998
    # Composite scores trigger LONG signals every 6th day
    composite_scores = [85.0 if i % 6 == 0 else 50.0 for i in range(n_days)]
    india_vix = [14.0 for _ in range(n_days)]

    df = pl.DataFrame({
        "Date": dates,
        "Open": opens,
        "High": highs,
        "Low": lows,
        "Close": prices,
        "CompositeScore": composite_scores,
        "India_VIX": india_vix,
    })

    bt_zero_cost = WalkForwardBacktester(include_costs=False)
    bt_with_costs = WalkForwardBacktester(include_costs=True)

    sim_zero = bt_zero_cost.simulate_signals(df, symbol="RELIANCE")
    sim_costs = bt_with_costs.simulate_signals(df, symbol="RELIANCE")

    metrics_zero = bt_zero_cost.calculate_metrics(sim_zero)
    metrics_costs = bt_with_costs.calculate_metrics(sim_costs)

    # Assert that net returns are strictly lower when costs are included
    valid_filter = (pl.col("EnterLong") == 1) & pl.col("ExitPrice").is_not_null()
    trades_zero = sim_zero.filter(valid_filter).get_column("TradeReturn").to_numpy()
    trades_costs = sim_costs.filter(valid_filter).get_column("TradeReturn").to_numpy()
    assert len(trades_costs) > 0
    assert np.all(trades_costs < trades_zero), "Net return with costs must be strictly lower for every trade"

    # Expectancy and Sharpe must drop
    assert metrics_costs["expectancy"] < metrics_zero["expectancy"]
    assert metrics_costs["sharpe"] < metrics_zero["sharpe"], (
        f"Expected Sharpe with costs ({metrics_costs['sharpe']:.2f}) < "
        f"zero-cost Sharpe ({metrics_zero['sharpe']:.2f})"
    )
    assert metrics_costs["profit_factor"] < metrics_zero["profit_factor"]


# ==============================================================================
# 5. PAPER TRADER INTEGRATION (COSTS & SLIPPAGE DEDUCTED)
# ==============================================================================

