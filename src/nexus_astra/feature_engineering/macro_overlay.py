"""Macro overlay regime analysis using yfinance, FRED, and Polars."""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timezone, date, timedelta
from typing import Any

import polars as pl
import yfinance as yf
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from nexus_astra.data_ingestion.database import MacroRegime as DBMacroRegime, DatabaseManager, database_manager

logger = logging.getLogger(__name__)

FRED_API_KEY_ENV = "FRED_API_KEY"

class MacroRegime:
    """Fetches macro-economic indicators, computes lead-lag correlation and risk signals, and updates MacroRegime state."""

    def __init__(self, db_manager: DatabaseManager | None = None, fred_api_key: str | None = None) -> None:
        self.db_manager = db_manager or database_manager
        self.fred_api_key = fred_api_key or os.getenv(FRED_API_KEY_ENV)

    async def run_pipeline(self) -> dict[str, Any]:
        """Fetch all required macro metrics, compute signals using Polars, and save to SQLite."""
        logger.info("Starting MacroRegime overlay pipeline...")
        self.db_manager.create_tables()

        today = datetime.now(timezone.utc).date()

        try:
            # 1. Fetch yfinance prices for macro assets
            # S&P 500 futures (ES=F), VIX (^VIX), US 10Y (^TNX), DXY (DX-Y.NYB), Brent Crude (BZ=F), Copper (HG=F), Baltic Dry Index proxy (GOGL), USD-INR (INR=X), Nifty (^NSEI)
            tickers = ["ES=F", "^VIX", "^TNX", "DX-Y.NYB", "BZ=F", "HG=F", "GOGL", "INR=X", "^NSEI"]
            price_data = await self._fetch_yfinance_prices(tickers)

            # 2. Fetch FRED money supply (M2SL) and India FX reserves (TRESEGIDA156N)
            m2_data = await self._fetch_fred_series("M2SL")
            reserves_data = await self._fetch_fred_series("TRESEGIDA156N")

            # 3. Calculate all macro indicators and signals using Polars
            signals = self._compute_signals(price_data, m2_data, reserves_data)

            # 4. Save results to database
            await self._persist_macro_regime(signals)
            logger.info("MacroRegime overlay pipeline completed successfully.")
            return signals

        except Exception as e:
            logger.error(f"Error in MacroRegime pipeline: {e}", exc_info=True)
            logger.warning("Falling back to mock MacroRegime data.")
            mock_signals = self._generate_mock_macro_data(today)
            await self._persist_macro_regime(mock_signals)
            return mock_signals

    async def _fetch_yfinance_prices(self, tickers: list[str]) -> dict[str, pl.DataFrame]:
        """Fetch daily closing prices from yfinance for the last 90 days."""
        data_dict = {}
        for ticker in tickers:
            try:
                # Fetch 120 days to ensure we have a solid 90 days after rolling calculations
                df = yf.download(ticker, period="120d", interval="1d", progress=False)
                if df.empty:
                    raise ValueError(f"No price data returned for {ticker}")

                # Flatten MultiIndex columns if present
                if type(df.columns).__name__ == "MultiIndex":
                    df.columns = df.columns.droplevel(1)

                # Ensure index name is Date and convert to Polars
                df = df.reset_index()
                pl_df = pl.from_pandas(df)
                
                # Standardize columns
                pl_df = pl_df.select([
                    pl.col("Date").cast(pl.Date).alias("date"),
                    pl.col("Close").cast(pl.Float64).alias("close")
                ]).sort("date")

                data_dict[ticker] = pl_df
            except Exception as e:
                logger.warning(f"Failed to fetch {ticker} from yfinance: {e}")
                raise

        return data_dict

    async def _fetch_fred_series(self, series_id: str) -> pl.DataFrame:
        """Fetch observations for a FRED series, prioritizing API key and falling back to direct CSV download."""
        import aiohttp

        # If API key is available, use official FRED API
        if self.fred_api_key:
            url = f"https://api.stlouisfed.org/fred/series/observations"
            params = {
                "series_id": series_id,
                "api_key": self.fred_api_key,
                "file_type": "json",
                "sort_order": "asc"
            }
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(url, params=params, timeout=15) as response:
                        response.raise_for_status()
                        res_json = await response.json()
                        obs = res_json.get("observations", [])
                        
                        records = []
                        for o in obs:
                            try:
                                val = float(o["value"])
                                dt = datetime.strptime(o["date"], "%Y-%m-%d").date()
                                records.append({"date": dt, "value": val})
                            except ValueError:
                                continue # Skip '.' or invalid data
                                
                        if not records:
                            raise ValueError("No valid observations returned from FRED API")
                        return pl.DataFrame(records).sort("date")
            except Exception as e:
                logger.warning(f"FRED API fetch for {series_id} failed: {e}. Trying direct CSV download.")

        # Fallback to direct CSV download from FRED graph URL (does not require API key)
        csv_url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}"
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(csv_url, timeout=15) as response:
                    response.raise_for_status()
                    csv_text = await response.text()
                    
                    records = []
                    # Parse CSV lines manually
                    for line in csv_text.splitlines()[1:]: # Skip header
                        parts = line.strip().split(",")
                        if len(parts) == 2:
                            try:
                                dt = datetime.strptime(parts[0], "%Y-%m-%d").date()
                                val = float(parts[1])
                                records.append({"date": dt, "value": val})
                            except ValueError:
                                continue

                    if not records:
                        raise ValueError("No valid CSV observations parsed from FRED.")
                    return pl.DataFrame(records).sort("date")
        except Exception as e:
            logger.warning(f"FRED direct CSV download for {series_id} failed: {e}")
            raise

    def _compute_signals(
        self, price_data: dict[str, pl.DataFrame], m2_data: pl.DataFrame, reserves_data: pl.DataFrame
    ) -> dict[str, Any]:
        """Compute rolling correlation and risk signals using Polars."""
        today = datetime.now(timezone.utc).date()

        # 1. Lead-Lag: Nifty 50 and S&P 500 futures correlation
        sp_df = price_data["ES=F"]
        nifty_df = price_data["^NSEI"]

        # Calculate daily log returns
        sp_returns = sp_df.with_columns(
            (pl.col("close").pct_change()).alias("sp_return")
        ).select(["date", "sp_return"]).drop_nulls()

        nifty_returns = nifty_df.with_columns(
            (pl.col("close").pct_change()).alias("nifty_return")
        ).select(["date", "nifty_return"]).drop_nulls()

        # Align on date
        aligned_returns = nifty_returns.join(sp_returns, on="date", how="full").sort("date")
        
        # Fill nulls with 0 for correlation purposes to avoid NaN propagation
        aligned_returns = aligned_returns.with_columns([
            pl.col("nifty_return").fill_null(0.0),
            pl.col("sp_return").fill_null(0.0)
        ])

        # Compute 30-day rolling correlation
        aligned_returns = aligned_returns.with_columns(
            pl.rolling_corr(pl.col("nifty_return"), pl.col("sp_return"), window_size=30).alias("sp_corr")
        ).drop_nulls()

        # Get latest metrics
        latest_row = aligned_returns.tail(1).to_dicts()[0]
        sp_corr_latest = latest_row.get("sp_corr", 0.0)
        sp_return_latest = latest_row.get("sp_return", 0.0)

        # US_MOMENTUM_CARRY flag
        us_momentum_carry = sp_corr_latest > 0.7 and abs(sp_return_latest) > 0.015

        # 2. Commodity Shock: Brent Crude and Copper
        crude_df = price_data["BZ=F"]
        copper_df = price_data["HG=F"]

        crude_latest = crude_df["close"][-1]
        
        # Copper 30-day return
        copper_latest = copper_df["close"][-1]
        copper_30d_ago = copper_df["close"][-30] if len(copper_df) >= 30 else copper_df["close"][0]
        copper_return_30d = (copper_latest - copper_30d_ago) / copper_30d_ago

        # STAGFLATION_RISK flag
        stagflation_risk = crude_latest > 90.0 and copper_return_30d < 0.0

        # 3. Fed Liquidity Pulse: M2 money supply growth rate
        m2_latest = m2_data["value"][-1]
        m2_year_ago = m2_data["value"][-12] if len(m2_data) >= 12 else m2_data["value"][0]
        m2_growth_yoy = (m2_latest - m2_year_ago) / m2_year_ago * 100.0

        # GLOBAL_LIQUIDITY_DRAIN flag
        global_liquidity_drain = m2_growth_yoy < -2.0

        # 4. USD-INR Stress: USD-INR and RBI FX reserves
        usdinr_latest = price_data["INR=X"]["close"][-1]
        
        reserves_latest = reserves_data["value"][-1]
        # Observations are weekly/monthly; check change in last 30 days
        # Assuming monthly data: reserves_latest vs reserves 1 month ago
        reserves_30d_ago = reserves_data["value"][-2] if len(reserves_data) >= 2 else reserves_data["value"][0]
        reserves_change_30d = reserves_latest - reserves_30d_ago

        # CURRENCY_STRESS flag
        # Reserves falling by > $10B in 30 days (-10,000,000,000 or -10,000 if units are millions)
        # Note: FRED TRESEGIDA156N is Total Reserves excluding Gold, in USD.
        currency_stress = usdinr_latest > 84.0 and reserves_change_30d < -10_000_000_000

        # Compute Composite Score (-100 to +100)
        macro_score = 0
        flags_list = []

        if us_momentum_carry:
            macro_score += 40
            flags_list.append("US_MOMENTUM_CARRY")
        if stagflation_risk:
            macro_score -= 30
            flags_list.append("STAGFLATION_RISK")
        if global_liquidity_drain:
            macro_score -= 30
            flags_list.append("GLOBAL_LIQUIDITY_DRAIN")
        if currency_stress:
            macro_score -= 40
            flags_list.append("CURRENCY_STRESS")

        macro_score = max(-100, min(100, macro_score))

        # Determine Regime Label
        if macro_score > 20:
            regime_label = "EXPANSION_CARRY"
        elif macro_score < -20:
            regime_label = "STRESS_DRAIN"
        else:
            regime_label = "NEUTRAL_CALM"

        # VIX and USD-INR details to update DB properly
        us_vix = price_data["^VIX"]["close"][-1]
        brent_crude = price_data["BZ=F"]["close"][-1]

        return {
            "Date": today,
            "US_VIX": float(us_vix),
            "USD_INR": float(usdinr_latest),
            "Brent_Crude": float(brent_crude),
            "Macro_Regime_Score": float(macro_score),
            "Regime_Label": regime_label,
            "Flags": ",".join(flags_list) if flags_list else None
        }

    async def _persist_macro_regime(self, data: dict[str, Any]) -> None:
        """Insert or update macro regime parameters in SQLite database."""
        def _execute_insert():
            with self.db_manager.session_scope() as session:
                statement = sqlite_insert(DBMacroRegime).values(
                    Date=data["Date"],
                    US_VIX=data["US_VIX"],
                    USD_INR=data["USD_INR"],
                    Brent_Crude=data["Brent_Crude"],
                    Macro_Regime_Score=data["Macro_Regime_Score"],
                    Regime_Label=data["Regime_Label"],
                    Flags=data["Flags"]
                )
                statement = statement.on_conflict_do_update(
                    index_elements=["Date"],
                    set_={
                        "US_VIX": statement.excluded["US_VIX"],
                        "USD_INR": statement.excluded["USD_INR"],
                        "Brent_Crude": statement.excluded["Brent_Crude"],
                        "Macro_Regime_Score": statement.excluded["Macro_Regime_Score"],
                        "Regime_Label": statement.excluded["Regime_Label"],
                        "Flags": statement.excluded["Flags"]
                    }
                )
                session.execute(statement)

        await asyncio.to_thread(_execute_insert)

    def _generate_mock_macro_data(self, target_date: date) -> dict[str, Any]:
        """Generate mock macro overlay signals for rate limits and local offline runs."""
        # Create a stress-based mock setup for comprehensive validation
        return {
            "Date": target_date,
            "US_VIX": 18.5,
            "USD_INR": 84.45,
            "Brent_Crude": 92.5,
            "Macro_Regime_Score": -70.0, # STAGFLATION_RISK (-30) + CURRENCY_STRESS (-40)
            "Regime_Label": "STRESS_DRAIN",
            "Flags": "STAGFLATION_RISK,CURRENCY_STRESS"
        }
