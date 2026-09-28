"""Binance Futures crypto metrics fetcher and aggregator using aiohttp and Polars."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import datetime, timezone
from typing import Any

import aiohttp
import polars as pl
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from .database import CryptoMetrics, DatabaseManager, database_manager

logger = logging.getLogger(__name__)


class CryptoDataEngine:
    """Ingest, aggregate, and store Binance Futures market metrics."""

    def __init__(self, db_manager: DatabaseManager | None = None) -> None:
        self.db_manager = db_manager or database_manager
        self.rest_base_url = "https://fapi.binance.com"
        self.ws_base_url = "wss://fstream.binance.com"
        self.symbols = ["BTCUSDT", "ETHUSDT"]

    async def run_pipeline(self) -> None:
        """Execute the ingestion pipeline for all configured symbols."""
        logger.info("Starting CryptoDataEngine pipeline...")
        self.db_manager.create_tables()

        async with aiohttp.ClientSession() as session:
            # 1. Fetch liquidations via WebSocket stream
            liquidations = await self._fetch_websocket_liquidations(session, duration_seconds=5.0)

            # 2. Process each symbol
            for symbol in self.symbols:
                try:
                    # Fetch premium index (funding rate)
                    premium_data = await self._fetch_with_retry(
                        session, f"{self.rest_base_url}/fapi/v1/premiumIndex", {"symbol": symbol}
                    )
                    funding_rate = float(premium_data.get("lastFundingRate", 0.0))

                    # Fetch open interest history
                    oi_history = await self._fetch_with_retry(
                        session, f"{self.rest_base_url}/futures/data/openInterestHist", {"symbol": symbol, "period": "1d", "limit": 10}
                    )

                    # Compute open interest changes and flags
                    oi_change_24h, oi_change_7d, flags = self._compute_metrics_and_flags(funding_rate, oi_history)

                    # Compute liquidation levels for this symbol
                    symbol_liq = [liq for liq in liquidations if liq["symbol"] == symbol]
                    liquidation_levels_json = self._aggregate_liquidations_to_json(symbol, symbol_liq)

                    # Persist to DB
                    await self._persist_metrics(
                        symbol=symbol,
                        funding_rate=funding_rate,
                        oi_change_24h=oi_change_24h,
                        oi_change_7d=oi_change_7d,
                        liquidation_levels_json=liquidation_levels_json,
                        flags=flags,
                    )
                    logger.info(f"Successfully processed and stored crypto metrics for {symbol}")

                except Exception as e:
                    logger.error(f"Error processing crypto metrics for {symbol}: {e}", exc_info=True)

    async def _fetch_with_retry(
        self, session: aiohttp.ClientSession, url: str, params: dict[str, Any] | None = None, retries: int = 3, backoff: float = 1.0
    ) -> Any:
        """Make HTTP GET requests with retries and exponential backoff."""
        for attempt in range(retries):
            try:
                async with session.get(url, params=params, timeout=10) as response:
                    if response.status == 429:
                        retry_after = int(response.headers.get("Retry-After", 5))
                        logger.warning(f"Rate limited (429) on {url}. Retrying after {retry_after} seconds...")
                        await asyncio.sleep(retry_after)
                        continue
                    
                    response.raise_for_status()
                    return await response.json()
            except Exception as e:
                if attempt == retries - 1:
                    logger.error(f"Failed to fetch {url} after {retries} attempts: {e}")
                    raise
                sleep_time = backoff * (2**attempt)
                logger.warning(f"Error fetching {url}: {e}. Retrying in {sleep_time:.1f}s...")
                await asyncio.sleep(sleep_time)

    async def _fetch_websocket_liquidations(self, session: aiohttp.ClientSession, duration_seconds: float = 5.0) -> list[dict[str, Any]]:
        """Connect to Binance Futures WebSocket stream and collect forced liquidation events."""
        stream_url = f"{self.ws_base_url}/stream?streams=btcusdt@forceOrder/ethusdt@forceOrder"
        logger.info(f"Connecting to Binance WebSocket stream: {stream_url} for {duration_seconds}s...")
        liquidations: list[dict[str, Any]] = []

        try:
            async with session.ws_connect(stream_url) as ws:
                start_time = time.time()
                while time.time() - start_time < duration_seconds:
                    remaining = duration_seconds - (time.time() - start_time)
                    if remaining <= 0:
                        break
                    try:
                        msg = await asyncio.wait_for(ws.receive_json(), timeout=max(0.1, remaining))
                        if isinstance(msg, dict) and "data" in msg and "o" in msg["data"]:
                            order_data = msg["data"]["o"]
                            liquidations.append({
                                "symbol": order_data.get("s"),
                                "price": float(order_data.get("p", 0.0)),
                                "qty": float(order_data.get("q", 0.0)),
                                "side": order_data.get("S"),
                                "time": int(order_data.get("T", 0)),
                            })
                    except asyncio.TimeoutError:
                        continue
        except Exception as e:
            logger.warning(f"WebSocket connection encountered an error: {e}. Falling back to empty liquidations list.")
        
        logger.info(f"WebSocket collected {len(liquidations)} liquidation events.")
        return liquidations

    def _compute_metrics_and_flags(self, funding_rate: float, oi_history: list[dict[str, Any]]) -> tuple[float, float, str]:
        """Compute 24h & 7d open interest change percentage and construct flags list."""
        flags_list: list[str] = []

        # 1. Funding rate flags
        # Funding rate threshold 0.1% = 0.001
        if funding_rate > 0.001:
            flags_list.append("FUNDING_EXTREME_LONG")
        elif funding_rate < -0.001:
            flags_list.append("FUNDING_EXTREME_SHORT")

        # 2. Open interest percentage changes
        if not oi_history or len(oi_history) < 2:
            return 0.0, 0.0, ",".join(flags_list)

        df = pl.DataFrame(oi_history)
        df = df.with_columns(
            pl.col("timestamp").cast(pl.Int64),
            pl.col("sumOpenInterest").cast(pl.Float64)
        ).sort("timestamp")

        latest_oi = df["sumOpenInterest"][-1]
        latest_ts = df["timestamp"][-1]

        # Calculate 24h change (1 day = 86,400,000 ms)
        target_24h = latest_ts - (24 * 60 * 60 * 1000)
        idx_24h = (df["timestamp"] - target_24h).abs().arg_min()
        oi_24h = df["sumOpenInterest"][idx_24h]
        oi_change_24h = ((latest_oi - oi_24h) / oi_24h * 100.0) if oi_24h > 0 else 0.0

        # Calculate 7d change (7 days = 604,800,000 ms)
        target_7d = latest_ts - (7 * 24 * 60 * 60 * 1000)
        idx_7d = (df["timestamp"] - target_7d).abs().arg_min()
        oi_7d = df["sumOpenInterest"][idx_7d]
        oi_change_7d = ((latest_oi - oi_7d) / oi_7d * 100.0) if oi_7d > 0 else 0.0

        # Open interest surge flag (>15% in 24h)
        if oi_change_24h > 15.0:
            flags_list.append("OI_SURGE")

        return oi_change_24h, oi_change_7d, ",".join(flags_list)

    def _aggregate_liquidations_to_json(self, symbol: str, symbol_liq: list[dict[str, Any]]) -> str:
        """Group force liquidations by price level and format to JSON string."""
        if not symbol_liq:
            return "[]"

        df = pl.DataFrame(symbol_liq)
        # Round BTC to nearest 10, ETH to nearest 1
        if symbol == "BTCUSDT":
            df = df.with_columns(((pl.col("price") / 10.0).round() * 10.0).alias("price_level"))
        else:
            df = df.with_columns(pl.col("price").round().alias("price_level"))

        # Group and aggregate
        grouped = df.group_by(["price_level", "side"]).agg(
            pl.col("qty").sum().alias("total_qty")
        ).sort("price_level")

        records = grouped.to_dicts()
        return json.dumps(records)

    async def _persist_metrics(
        self, symbol: str, funding_rate: float, oi_change_24h: float, oi_change_7d: float, liquidation_levels_json: str, flags: str
    ) -> None:
        """Insert or update metrics in SQLite database."""
        now_utc = datetime.now(timezone.utc)
        payload = {
            "Symbol": symbol,
            "Date": now_utc,
            "FundingRate": funding_rate,
            "OI_Change_24h": oi_change_24h,
            "OI_Change_7d": oi_change_7d,
            "Liquidation_Levels": liquidation_levels_json,
            "Flags": flags if flags else None,
        }

        def _execute_insert():
            with self.db_manager.session_scope() as session:
                statement = sqlite_insert(CryptoMetrics).values(payload)
                statement = statement.on_conflict_do_update(
                    index_elements=["Symbol", "Date"],
                    set_={
                        "FundingRate": statement.excluded["FundingRate"],
                        "OI_Change_24h": statement.excluded["OI_Change_24h"],
                        "OI_Change_7d": statement.excluded["OI_Change_7d"],
                        "Liquidation_Levels": statement.excluded["Liquidation_Levels"],
                        "Flags": statement.excluded["Flags"],
                    },
                )
                session.execute(statement)

        await asyncio.to_thread(_execute_insert)
