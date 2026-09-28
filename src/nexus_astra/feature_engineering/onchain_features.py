"""On-chain intelligence and smart money flow feature engineering using Polars."""

from __future__ import annotations

import asyncio
import logging
import os
import time
from datetime import datetime, timezone, timedelta
from typing import Any

import aiohttp
import polars as pl

logger = logging.getLogger(__name__)

WHALE_ALERT_API_KEY_ENV = "WHALE_ALERT_API_KEY"


class WhaleIntelligence:
    """Analyze on-chain smart money flows including whale movements, stablecoin supply, and miner pressure."""

    def __init__(self, api_key: str | None = None) -> None:
        self.api_key = api_key or os.getenv(WHALE_ALERT_API_KEY_ENV)
        self.whale_alert_url = "https://api.whale-alert.io/v1/transactions"
        self.coingecko_base_url = "https://api.coingecko.com/api/v3"
        self.blockchair_base_url = "https://api.blockchair.com"

    async def fetch_whale_flows(self, session: aiohttp.ClientSession) -> pl.DataFrame:
        """Fetch transactions > $50M from Whale Alert API.

        Falls back to mock data if API key is missing or request fails.
        """
        # Calculate time window (last 24 hours)
        now_ts = int(time.time())
        start_ts = now_ts - 86400

        # If no API key, use mock data
        if not self.api_key:
            logger.warning("Whale Alert API key is missing. Using mock transactions.")
            return self._generate_mock_whale_flows(start_ts, now_ts)

        params = {
            "api_key": self.api_key,
            "start": start_ts,
            "end": now_ts,
            "min_value": 50000000,  # $50M
        }

        try:
            async with session.get(self.whale_alert_url, params=params, timeout=15) as r:
                if r.status == 429:
                    logger.warning("Whale Alert API rate limit hit. Using mock transactions.")
                    return self._generate_mock_whale_flows(start_ts, now_ts)
                
                r.raise_for_status()
                data = await r.json()
                
                transactions = data.get("transactions", [])
                if not transactions:
                    return pl.DataFrame(schema=self._whale_flows_schema())
                
                # Convert to Polars DataFrame using pure Polars
                normalized_txs = []
                for tx in transactions:
                    from_owner_type = tx.get("from", {}).get("owner_type", "wallet")
                    to_owner_type = tx.get("to", {}).get("owner_type", "wallet")
                    normalized_txs.append({
                        "blockchain": tx.get("blockchain"),
                        "symbol": tx.get("symbol", "").lower(),
                        "amount_usd": float(tx.get("amount_usd", 0.0)),
                        "from_owner_type": from_owner_type,
                        "to_owner_type": to_owner_type,
                        "timestamp": int(tx.get("timestamp", 0))
                    })
                
                return pl.DataFrame(normalized_txs, schema=self._whale_flows_schema())
        except Exception as e:
            logger.error(f"Failed to fetch Whale Alert transactions: {e}. Falling back to mock data.")
            return self._generate_mock_whale_flows(start_ts, now_ts)

    async def fetch_stablecoin_velocity(self, session: aiohttp.ClientSession) -> pl.DataFrame:
        """Fetch 7-day USDT and USDC market caps from CoinGecko.

        Returns a Polars DataFrame with columns: date, tether_mcap, usd-coin_mcap
        """
        coins = ["tether", "usd-coin"]
        data_dict = {}

        for coin in coins:
            url = f"{self.coingecko_base_url}/coins/{coin}/market_chart"
            params = {"vs_currency": "usd", "days": "7"}
            try:
                async with session.get(url, params=params, timeout=15) as r:
                    if r.status == 429:
                        logger.warning(f"CoinGecko rate limited for {coin}. Using mock stablecoin data.")
                        return self._generate_mock_stablecoin_data()
                    
                    r.raise_for_status()
                    res = await r.json()
                    market_caps = res.get("market_caps", [])
                    if not market_caps:
                        raise ValueError(f"No market cap data returned for {coin}")
                    
                    # Convert to dataframe using pure Polars
                    df_coin = pl.DataFrame(
                        market_caps, schema=[("timestamp", pl.Int64), (f"{coin}_mcap", pl.Float64)]
                    )
                    
                    # Convert timestamp to date and aggregate
                    df_coin = df_coin.with_columns(
                        pl.from_epoch(pl.col("timestamp"), time_unit="ms").cast(pl.Date).alias("date")
                    ).group_by("date").agg(pl.col(f"{coin}_mcap").last())
                    
                    data_dict[coin] = df_coin
            except Exception as e:
                logger.error(f"Failed to fetch CoinGecko market cap for {coin}: {e}. Falling back to mock data.")
                return self._generate_mock_stablecoin_data()

        # Join the USDT and USDC dataframes using Polars
        if "tether" in data_dict and "usd-coin" in data_dict:
            usdt_df = data_dict["tether"]
            usdc_df = data_dict["usd-coin"]
            return usdt_df.join(usdc_df, on="date", how="inner").sort("date")
        
        return self._generate_mock_stablecoin_data()

    async def fetch_miner_flow_proxy(self, session: aiohttp.ClientSession) -> pl.DataFrame:
        """Fetch recent blocks from Blockchair API to compute miner pressure proxy.

        Returns a Polars DataFrame of recent blocks.
        """
        url = f"{self.blockchair_base_url}/bitcoin/blocks"
        params = {"limit": 100}
        try:
            async with session.get(url, params=params, timeout=15) as r:
                if r.status == 429:
                    logger.warning("Blockchair API rate limited. Using mock blocks data.")
                    return self._generate_mock_blocks_data()
                
                r.raise_for_status()
                res = await r.json()
                blocks_data = res.get("data", [])
                
                if not blocks_data:
                    return self._generate_mock_blocks_data()
                
                # Convert to Polars DataFrame
                df = pl.DataFrame(
                    blocks_data,
                    schema={
                        "id": pl.Int64,
                        "fee_total": pl.Int64,
                        "generation": pl.Int64,
                    }
                )
                return df
        except Exception as e:
            logger.error(f"Failed to fetch Blockchair blocks data: {e}. Falling back to mock data.")
            return self._generate_mock_blocks_data()

    async def analyze(self, session: aiohttp.ClientSession | None = None) -> dict[str, Any]:
        """Fetch all data points, compute component scores, flags, and composite score.

        Uses pure Polars for calculations.
        """
        async def run_analysis(sess: aiohttp.ClientSession) -> dict[str, Any]:
            # Fetch datasets concurrently
            whale_df, stable_df, miner_df = await asyncio.gather(
                self.fetch_whale_flows(sess),
                self.fetch_stablecoin_velocity(sess),
                self.fetch_miner_flow_proxy(sess)
            )

            # 1. Compute Whale Flow Score (40% weight)
            # Exchange inflows are bearish (selling pressure). Outflows are bullish.
            flags = []
            
            # Filter for btc and eth
            btc_eth_whales = whale_df.filter(pl.col("symbol").is_in(["btc", "eth"]))
            
            inflows = btc_eth_whales.filter(
                (pl.col("from_owner_type") == "wallet") & (pl.col("to_owner_type") == "exchange")
            )
            outflows = btc_eth_whales.filter(
                (pl.col("from_owner_type") == "exchange") & (pl.col("to_owner_type") == "wallet")
            )

            total_inflow = inflows.select(pl.col("amount_usd").sum()).item() or 0.0
            total_outflow = outflows.select(pl.col("amount_usd").sum()).item() or 0.0

            if total_inflow > 0 or total_outflow > 0:
                outflow_ratio = total_outflow / (total_inflow + total_outflow)
                whale_score = float(outflow_ratio * 100.0)
            else:
                whale_score = 50.0  # Neutral

            # Flags for whale flows
            if total_inflow > 100000000:  # Inflows > $100M
                flags.append("EXCHANGE_INFLOW_SURGE")
            if total_outflow > 100000000:  # Outflows > $100M
                flags.append("EXCHANGE_OUTFLOW_SURGE")

            # 2. Compute Stablecoin Velocity Score (35% weight)
            # growth in USDT + USDC supply over 7 days
            if stable_df.height >= 2:
                stable_total = stable_df.with_columns(
                    (pl.col("tether_mcap") + pl.col("usd-coin_mcap")).alias("total_supply")
                ).sort("date")

                supply_start = stable_total["total_supply"][0]
                supply_end = stable_total["total_supply"][-1]

                supply_growth_7d = ((supply_end - supply_start) / supply_start) * 100.0 if supply_start > 0 else 0.0
            else:
                supply_growth_7d = 0.0

            # Scale score: +4% growth is 100, -4% is 0, 0% is 50
            stable_score = 50.0 + (supply_growth_7d * 12.5)
            stable_score = float(max(0.0, min(100.0, stable_score)))

            # Flag: BUYING_POWER_BUILDING if supply growth > 2% in 7 days
            if supply_growth_7d > 2.0:
                flags.append("BUYING_POWER_BUILDING")

            # 3. Compute Miner Pressure Score (25% weight)
            # High fee-to-generation ratio means low miner selling pressure (bullish / 100 score).
            # Low fee-to-generation ratio means high miner selling pressure (bearish / 0 score).
            if miner_df.height > 0:
                miner_calc = miner_df.with_columns(
                    (pl.col("fee_total") / pl.col("generation")).alias("fee_to_gen_ratio")
                )
                avg_fee_ratio = miner_calc.select(pl.col("fee_to_gen_ratio").mean()).item() or 0.0
                
                # Scale score: avg_fee_ratio >= 10% is 100, <= 2% is 0
                miner_score = (avg_fee_ratio - 0.02) / 0.08 * 100.0
                miner_score = float(max(0.0, min(100.0, miner_score)))
            else:
                miner_score = 50.0

            # Composite Score (0-100)
            composite_score = (0.40 * whale_score) + (0.35 * stable_score) + (0.25 * miner_score)

            return {
                "whale_flow_score": whale_score,
                "stablecoin_velocity_score": stable_score,
                "miner_pressure_score": miner_score,
                "crypto_smart_money_score": float(composite_score),
                "stablecoin_growth_7d": float(supply_growth_7d),
                "flags": ",".join(flags),
            }

        if session is not None:
            return await run_analysis(session)
        
        async with aiohttp.ClientSession() as sess:
            return await run_analysis(sess)

    def _whale_flows_schema(self) -> dict[str, Any]:
        return {
            "blockchain": pl.String,
            "symbol": pl.String,
            "amount_usd": pl.Float64,
            "from_owner_type": pl.String,
            "to_owner_type": pl.String,
            "timestamp": pl.Int64
        }

    def _generate_mock_whale_flows(self, start_ts: int, end_ts: int) -> pl.DataFrame:
        """Return dummy large transactions to keep processing alive during outages/dev."""
        mock_data = [
            # $80M Inflow (Bearish)
            {
                "blockchain": "bitcoin",
                "symbol": "btc",
                "amount_usd": 80000000.0,
                "from_owner_type": "wallet",
                "to_owner_type": "exchange",
                "timestamp": start_ts + 3600
            },
            # $120M Outflow (Bullish)
            {
                "blockchain": "ethereum",
                "symbol": "eth",
                "amount_usd": 120000000.0,
                "from_owner_type": "exchange",
                "to_owner_type": "wallet",
                "timestamp": start_ts + 7200
            },
            # $60M Outflow (Bullish)
            {
                "blockchain": "bitcoin",
                "symbol": "btc",
                "amount_usd": 60000000.0,
                "from_owner_type": "exchange",
                "to_owner_type": "wallet",
                "timestamp": start_ts + 10800
            }
        ]
        return pl.DataFrame(mock_data, schema=self._whale_flows_schema())

    def _generate_mock_stablecoin_data(self) -> pl.DataFrame:
        """Return dummy stablecoin market cap data representing ~2.5% supply growth (bullish)."""
        today = datetime.now(timezone.utc).date()
        mock_records = []
        
        # Base mcaps: USDT = $110B, USDC = $32B
        base_usdt = 110_000_000_000.0
        base_usdc = 32_000_000_000.0
        
        for i in range(8):
            d = today - timedelta(days=7 - i)
            # Simulate a 2.4% linear growth over 7 days (0.3% per day)
            growth_mult = 1.0 + (i * 0.0034)
            mock_records.append({
                "date": d,
                "tether_mcap": base_usdt * growth_mult,
                "usd-coin_mcap": base_usdc * growth_mult
            })
            
        return pl.DataFrame(mock_records)

    def _generate_mock_blocks_data(self) -> pl.DataFrame:
        """Return 100 blocks of mock data with realistic miner reward metrics."""
        mock_blocks = []
        for i in range(100):
            # subsidy is 3.125 BTC = 312,500,000 satoshis
            generation = 312500000
            # Total fees between 6,000,000 and 32,000,000 satoshis (approx 2% - 10% of subsidy)
            fee_total = int(6000000 + (i * 260000) % 26000000)
            mock_blocks.append({
                "id": 840000 + i,
                "fee_total": fee_total,
                "generation": generation
            })
        return pl.DataFrame(mock_blocks)
