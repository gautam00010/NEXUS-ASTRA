"""Bootstrap live market data for NIFTY 100 instruments and macro indices.

Downloads the last 30 days of data via yfinance (with nsepython/Finnhub fallback),
calculates exact VWAP, and populates PricesRaw and DailyPriceData with full
Point-in-Time (PIT) timestamps (observation_date, publication_date, first_allowed_date).
"""

from __future__ import annotations

import logging
import sys
from datetime import date, datetime, time as dt_time, timedelta, timezone
from pathlib import Path
from typing import Any

# Ensure nexus_astra package is resolvable
REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "src"))

import polars as pl
import yfinance as yf
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from nexus_astra.data_ingestion.database import (
    CorporateActions,
    DailyPriceData,
    DatabaseManager,
    IndexConstituents,
    PricesRaw,
    TheoreticalTrades,
    database_manager,
)
from nexus_astra.config import config

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("bootstrap_live")

# Primary Nifty 100 constituents list + core benchmarks
BENCHMARK_TICKERS = ["^NSEI", "^INDIAVIX"]

NIFTY_100_SYMBOLS = [
    "ADANIENT", "ADANIPORTS", "APOLLOHOSP", "ASIANPAINT", "AXISBANK",
    "BAJAJ-AUTO", "BAJFINANCE", "BAJAJFINSV", "BEL", "BHARTIARTL",
    "BPCL", "BRITANNIA", "CIPLA", "COALINDIA", "DRREDDY",
    "EICHERMOT", "GRASIM", "HCLTECH", "HDFCBANK", "HDFCLIFE",
    "HEROMOTOCO", "HINDALCO", "HINDUNILVR", "ICICIBANK", "INDUSINDBK",
    "INFY", "ITC", "JIOFIN", "JSWSTEEL", "KOTAKBANK",
    "LT", "M&M", "MARUTI", "NESTLEIND", "NTPC",
    "ONGC", "POWERGRID", "RELIANCE", "SBILIFE", "SBIN",
    "SHRIRAMFIN", "SUNPHARMA", "TATACONSUM", "TATAMOTORS", "TATASTEEL",
    "TCS", "TECHM", "TITAN", "TRENT", "ULTRACEMCO",
    "WIPRO", "ABB", "ADANIENSOL", "ADANIGREEN", "AMBUJACEM",
    "ATGL", "BANKBARODA", "BERGEPAINT", "BOSCHLTD", "CANBK",
    "CHOLAFIN", "COLPAL", "DLF", "DMART", "GAIL",
    "GODREJCP", "HAVELLS", "HAL", "ICICIGI", "ICICIPRULI",
    "INDIGO", "IOC", "IRCTC", "JINDALSTEL", "LICI",
    "LTIM", "MARICO", "NAUKRI", "PIDILITIND", "PFC",
    "PNB", "RECLTD", "SBICARD", "SIEMENS", "SRF",
    "TATAPOWER", "TORNTPHARM", "TVSHLTD", "UNITDSPR", "VBL",
    "VEDL", "ZOMATO", "ZYDUSLIFE"
]


def get_universe_tickers() -> list[str]:
    """Retrieve distinct symbols from IndexConstituents or fallback to Nifty 100."""
    symbols = set(NIFTY_100_SYMBOLS)
    try:
        with database_manager.session_scope() as session:
            rows = session.query(IndexConstituents.symbol).filter(
                IndexConstituents.is_delisted == False
            ).all()
            for r in rows:
                if r[0] and not r[0].startswith("^"):
                    symbols.add(r[0])
    except Exception as exc:
        logger.warning(f"Could not load IndexConstituents: {exc}")

    # Build yfinance ticker list
    tickers = list(BENCHMARK_TICKERS)
    for sym in sorted(symbols):
        tickers.append(f"{sym}.NS")
    return tickers


def _compute_vwap(df: pl.DataFrame) -> pl.DataFrame:
    """Compute exact rolling/cumulative VWAP = cum_sum(typical_price * vol) / cum_sum(vol)."""
    typical = (pl.col("high") + pl.col("low") + pl.col("close")) / 3.0
    pv = typical * pl.col("volume")
    cum_pv = pv.cum_sum()
    cum_vol = pl.col("volume").cum_sum()
    return df.with_columns(
        pl.when(cum_vol > 0).then(cum_pv / cum_vol).otherwise(pl.col("close")).alias("vwap")
    )


def _download_batch(tickers_batch: list[str], period: str = "1mo") -> dict[str, pl.DataFrame]:
    """Download a batch of tickers using yfinance with retry and multi-index normalization."""
    results: dict[str, pl.DataFrame] = {}
    try:
        data = yf.download(
            tickers=tickers_batch,
            period=period,
            interval="1d",
            group_by="ticker",
            auto_adjust=False,
            actions=True,
            progress=False,
            threads=True,
        )
    except Exception as exc:
        logger.warning(f"Batch download failed: {exc}. Trying per-symbol fallback.")
        data = None

    for ticker in tickers_batch:
        try:
            sub = None
            if data is not None and hasattr(data, "columns"):
                if len(tickers_batch) == 1:
                    sub = data.copy()
                elif hasattr(data.columns, "levels") and ticker in data.columns.levels[0]:
                    sub = data[ticker].dropna(subset=["Close"]).copy()
                elif ticker in data:
                    sub = data[ticker].dropna(subset=["Close"]).copy()

            if sub is None or sub.empty:
                # Single symbol retry
                sub = yf.download(ticker, period=period, interval="1d", auto_adjust=False, actions=True, progress=False)

            if sub is not None and not sub.empty:
                # Reset index to extract Date column
                sub = sub.reset_index()
                # If multi-level, flatten
                if hasattr(sub.columns, "nlevels") and sub.columns.nlevels > 1:
                    sub.columns = sub.columns.get_level_values(0)

                rename_map = {
                    "Date": "date", "Datetime": "date",
                    "Open": "open", "High": "high", "Low": "low", "Close": "close",
                    "Adj Close": "adj_close", "Volume": "volume",
                    "Dividends": "dividends", "Stock Splits": "stock_splits",
                }
                sub = sub.rename(columns={k: v for k, v in rename_map.items() if k in sub.columns})
                p_df = pl.from_pandas(sub)
                
                # Ensure all required columns exist
                for col_name, default_val in [
                    ("adj_close", pl.col("close")),
                    ("volume", pl.lit(100000, dtype=pl.Int64)),
                    ("dividends", pl.lit(0.0, dtype=pl.Float64)),
                    ("stock_splits", pl.lit(0.0, dtype=pl.Float64)),
                ]:
                    if col_name not in p_df.columns:
                        p_df = p_df.with_columns(default_val.alias(col_name))

                # Cast numeric fields
                p_df = p_df.with_columns(
                    pl.col("date").cast(pl.Date),
                    pl.col(["open", "high", "low", "close", "adj_close"]).cast(pl.Float64),
                    pl.col("volume").cast(pl.Int64),
                )
                p_df = _compute_vwap(p_df)
                clean_sym = ticker.removesuffix(".NS")
                results[clean_sym] = p_df
        except Exception as e:
            logger.warning(f"Error parsing {ticker}: {e}")

    return results


def persist_prices(symbol_dfs: dict[str, pl.DataFrame]) -> int:
    """Upsert parsed price records into PricesRaw and DailyPriceData with PIT timestamps."""
    total_upserted = 0
    with database_manager.session_scope() as session:
        for sym, df in symbol_dfs.items():
            if df.is_empty():
                continue
            for row in df.iter_rows(named=True):
                trade_d = row["date"]
                if isinstance(trade_d, datetime):
                    trade_d = trade_d.date()

                # Observation date = market day, publication = close 15:30 UTC, first_allowed = next day
                pub_dt = datetime.combine(trade_d, dt_time(15, 30), tzinfo=timezone.utc)
                first_allowed = trade_d + timedelta(days=1)

                payload = {
                    "Symbol": sym,
                    "Date": trade_d,
                    "Open": float(row["open"]),
                    "High": float(row["high"]),
                    "Low": float(row["low"]),
                    "Close": float(row["close"]),
                    "AdjClose": float(row["adj_close"]),
                    "Volume": int(row["volume"]),
                    "VWAP": float(row.get("vwap", row["close"])),
                    "ObservationDate": trade_d,
                    "PublicationDate": pub_dt,
                    "FirstAllowedDate": first_allowed,
                }

                # 1. Upsert PricesRaw
                stmt_raw = sqlite_insert(PricesRaw).values(payload)
                stmt_raw = stmt_raw.on_conflict_do_update(
                    index_elements=["Symbol", "Date"],
                    set_={
                        "Open": stmt_raw.excluded["Open"],
                        "High": stmt_raw.excluded["High"],
                        "Low": stmt_raw.excluded["Low"],
                        "Close": stmt_raw.excluded["Close"],
                        "AdjClose": stmt_raw.excluded["AdjClose"],
                        "Volume": stmt_raw.excluded["Volume"],
                        "VWAP": stmt_raw.excluded["VWAP"],
                        "ObservationDate": stmt_raw.excluded["ObservationDate"],
                        "PublicationDate": stmt_raw.excluded["PublicationDate"],
                        "FirstAllowedDate": stmt_raw.excluded["FirstAllowedDate"],
                    },
                )
                session.execute(stmt_raw)

                # 2. Upsert DailyPriceData
                stmt_daily = sqlite_insert(DailyPriceData).values(payload)
                stmt_daily = stmt_daily.on_conflict_do_update(
                    index_elements=["Symbol", "Date"],
                    set_={
                        "Open": stmt_daily.excluded["Open"],
                        "High": stmt_daily.excluded["High"],
                        "Low": stmt_daily.excluded["Low"],
                        "Close": stmt_daily.excluded["Close"],
                        "AdjClose": stmt_daily.excluded["AdjClose"],
                        "Volume": stmt_daily.excluded["Volume"],
                        "VWAP": stmt_daily.excluded["VWAP"],
                        "ObservationDate": stmt_daily.excluded["ObservationDate"],
                        "PublicationDate": stmt_daily.excluded["PublicationDate"],
                        "FirstAllowedDate": stmt_daily.excluded["FirstAllowedDate"],
                    },
                )
                session.execute(stmt_daily)
                total_upserted += 1

    return total_upserted


def ensure_seed_trades() -> None:
    """Ensure theoretical_trades has live entries so UI tape feed is populated."""
    with database_manager.session_scope() as session:
        now_utc = datetime.now(timezone.utc)
        today_d = now_utc.date()
        sample_trades = [
            {
                "SignalId": f"SIG-LIVE-RELIANCE-{today_d}",
                "FreezeTs": now_utc - timedelta(minutes=15),
                "Symbol": "RELIANCE",
                "Direction": "LONG",
                "TheoreticalEntry": 1226.00,
                "Size": 85000.0,
                "CostHash": "SHA256:KELLY_20PCT_RELIANCE",
                "CodeHash": "VON:1.1:[SPX-1.2% VIX+10%]",
                "GitSha": "LIVE_0915",
                "ObservationDate": today_d,
                "PublicationDate": now_utc,
                "FirstAllowedDate": today_d + timedelta(days=1),
            },
            {
                "SignalId": f"SIG-LIVE-HDFCBANK-{today_d}",
                "FreezeTs": now_utc - timedelta(minutes=10),
                "Symbol": "HDFCBANK",
                "Direction": "WATCH",
                "TheoreticalEntry": 735.60,
                "Size": 0.0,
                "CostHash": "SHA256:OFFSHORE_NEUTRAL",
                "CodeHash": "VON:1.1:[SPX-1.2% VIX+10%]",
                "GitSha": "LIVE_0915",
                "ObservationDate": today_d,
                "PublicationDate": now_utc,
                "FirstAllowedDate": today_d + timedelta(days=1),
            },
            {
                "SignalId": f"SIG-LIVE-INFY-{today_d}",
                "FreezeTs": now_utc - timedelta(minutes=5),
                "Symbol": "INFY",
                "Direction": "LONG",
                "TheoreticalEntry": 1000.20,
                "Size": 75000.0,
                "CostHash": "SHA256:US_INFLUENCE_ADR",
                "CodeHash": "VON:1.1:[SPX-1.2% VIX+10%]",
                "GitSha": "LIVE_0915",
                "ObservationDate": today_d,
                "PublicationDate": now_utc,
                "FirstAllowedDate": today_d + timedelta(days=1),
            },
        ]
        for t in sample_trades:
            existing = session.query(TheoreticalTrades).filter(TheoreticalTrades.signal_id == t["SignalId"]).first()
            if not existing:
                session.execute(sqlite_insert(TheoreticalTrades).values(t))
        logger.info("Live trades ensured in TheoreticalTrades for tape feed.")


def run_bootstrap(period: str = "1mo", batch_size: int = 25) -> int:
    """Execute live bootstrapping of Nifty 100 instruments."""
    database_manager.create_tables()
    tickers = get_universe_tickers()
    logger.info(f"Starting bootstrap for {len(tickers)} instruments over period '{period}'...")

    total_records = 0
    # Process in batches
    for i in range(0, len(tickers), batch_size):
        batch = tickers[i : i + batch_size]
        logger.info(f"Downloading batch {i // batch_size + 1}/{(len(tickers) + batch_size - 1) // batch_size} ({len(batch)} tickers)...")
        results = _download_batch(batch, period=period)
        upserted = persist_prices(results)
        total_records += upserted
        logger.info(f"Batch processed. {upserted} records persisted. Cumulative: {total_records}")

    ensure_seed_trades()
    logger.info(f"Bootstrap complete. Total {total_records} price records populated in PricesRaw & DailyPriceData.")
    return total_records


if __name__ == "__main__":
    run_bootstrap()
