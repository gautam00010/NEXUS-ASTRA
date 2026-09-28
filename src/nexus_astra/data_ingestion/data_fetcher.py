"""Asynchronous market-data ingestion for NEXUS-ASTRA."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any

import polars as pl
import yfinance as yf
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

logger = logging.getLogger(__name__)

from .database import (
    CorporateActions,
    DailyPriceData,
    DatabaseManager,
    InstitutionalFlows,
    MacroRegime,
    PricesRaw,
    database_manager,
)


YEARS_OF_HISTORY = 5
DEFAULT_INTERVAL = "1d"

def _load_universe_tickers() -> list[str]:
    """Return list of yfinance-compatible tickers. Indices: ^NSEI. NSE stocks: SYMBOL.NS. Crypto: BTC-USD."""
    tickers: list[str] = ["^NSEI", "BTC-USD"]
    try:
        from scripts.populate_constituents import load_nifty_500_pit
        today = datetime.now(timezone.utc).date()
        for sym in load_nifty_500_pit(today):
            if sym and not sym.startswith("^"):
                ns_sym = sym if sym.endswith(".NS") else f"{sym}.NS"
                if ns_sym not in tickers:
                    tickers.append(ns_sym)
    except Exception as e:
        logger.warning(f"Could not load Nifty 500 PIT: {e} – using ^NSEI + BTC-USD only")
    return tickers

DAILY_PRICE_TICKERS: list[str] = _load_universe_tickers()

MACRO_TICKERS = {
    "^INDIAVIX": "^INDIAVIX",
    "INR=X": "INR=X",
}


@dataclass(frozen=True)
class FetchResult:
    """Container for a downloaded and normalized Polars frame."""

    symbol: str
    frame: pl.DataFrame


class MarketDataFetcher:
    """Download and persist historical market data with async orchestration."""

    def __init__(self, db_manager: DatabaseManager | None = None) -> None:
        self.db_manager = db_manager or database_manager

    async def fetch_all(self) -> None:
        """Fetch the configured instruments and persist them into SQLite."""

        daily_frames, macro_frames, fii_dii_raw = await asyncio.gather(
            self._fetch_daily_price_data(),
            self._fetch_macro_regime_data(),
            self._fetch_fii_dii_flows(),
        )

        self._persist_daily_price_data(daily_frames)
        self._persist_macro_regime_data(macro_frames)
        self._persist_fii_dii_flows(fii_dii_raw)

        # Bootstrap FII/DII flows historically if empty/insufficient
        self.bootstrap_historical_flows()

    async def _fetch_fii_dii_flows(self) -> list[dict[str, Any]]:
        """Fetch current FII/DII flow data from NSE API."""
        url = "https://www.nseindia.com/api/fiidiiTradeReact"
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
            ),
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "en-US,en;q=0.9",
            "Connection": "keep-alive",
            "Referer": "https://www.nseindia.com/reports/fii-dii",
        }

        def _get_api_data():
            import requests
            session = requests.Session()
            session.headers.update(headers)
            try:
                # Prime session
                session.get("https://www.nseindia.com", timeout=10)
                session.get("https://www.nseindia.com/reports/fii-dii", timeout=10)
                response = session.get(url, timeout=10)
                response.raise_for_status()
                return response.json()
            except Exception as e:
                import logging
                logging.getLogger(__name__).warning(f"Error fetching FII/DII data: {e}")
                return []

        return await asyncio.to_thread(_get_api_data)

    def _persist_fii_dii_flows(self, raw_flows: list[dict[str, Any]]) -> None:
        """Parse and persist raw FII/DII flow records."""
        if not raw_flows:
            return

        self.db_manager.create_tables()

        # Group raw flows by date
        by_date: dict[str, dict[str, Any]] = {}
        for item in raw_flows:
            dt_str = item.get("date")
            if not dt_str:
                continue
            if dt_str not in by_date:
                by_date[dt_str] = {}
            category = item.get("category", "")
            if "DII" in category:
                by_date[dt_str]["DII"] = item
            elif "FII" in category:
                by_date[dt_str]["FII"] = item

        with self.db_manager.session_scope() as session:
            for dt_str, data in by_date.items():
                try:
                    flow_date = datetime.strptime(dt_str, "%d-%b-%Y").date()
                except Exception:
                    continue

                dii = data.get("DII", {})
                fii = data.get("FII", {})

                payload = {
                    "Date": flow_date,
                    "FII_Buy": float(fii.get("buyValue", 0.0) or 0.0),
                    "FII_Sell": float(fii.get("sellValue", 0.0) or 0.0),
                    "Net_FII": float(fii.get("netValue", 0.0) or 0.0),
                    "DII_Buy": float(dii.get("buyValue", 0.0) or 0.0),
                    "DII_Sell": float(dii.get("sellValue", 0.0) or 0.0),
                    "Net_DII": float(dii.get("netValue", 0.0) or 0.0),
                }

                statement = sqlite_insert(InstitutionalFlows).values(payload)
                statement = statement.on_conflict_do_update(
                    index_elements=["Date"],
                    set_={
                        "FII_Buy": statement.excluded["FII_Buy"],
                        "FII_Sell": statement.excluded["FII_Sell"],
                        "Net_FII": statement.excluded["Net_FII"],
                        "DII_Buy": statement.excluded["DII_Buy"],
                        "DII_Sell": statement.excluded["DII_Sell"],
                        "Net_DII": statement.excluded["Net_DII"],
                    },
                )
                session.execute(statement)

    def bootstrap_historical_flows(self) -> str | None:
        """Verify real FII/DII history exists; if low, return DATA_FAIL and never synthesize fake data."""
        with self.db_manager.session_scope() as session:
            existing_count = session.query(InstitutionalFlows).count()
            if existing_count < 10:
                logger.error("DATA_FAIL: Real FII/DII flow records are insufficient (< 10). Never synthesizing fake flows.")
                return "DATA_FAIL"
        return None

    async def _fetch_daily_price_data(self) -> list[FetchResult]:
        tasks = [self._download_symbol(ticker) for ticker in DAILY_PRICE_TICKERS]
        downloaded = await asyncio.gather(*tasks, return_exceptions=True)
        results = []
        for ticker, frame_or_exc in zip(DAILY_PRICE_TICKERS, downloaded):
            if isinstance(frame_or_exc, Exception):
                logger.warning(f"Download failed for {ticker}: {frame_or_exc}")
                results.append(FetchResult(symbol=ticker, frame=pl.DataFrame()))
            else:
                results.append(FetchResult(symbol=ticker, frame=frame_or_exc))
        return results

    async def _fetch_macro_regime_data(self) -> list[FetchResult]:
        tasks = [self._download_symbol(symbol) for symbol in MACRO_TICKERS]
        downloaded = await asyncio.gather(*tasks)
        return [FetchResult(symbol=symbol, frame=frame) for symbol, frame in zip(MACRO_TICKERS, downloaded)]

    def _download_binance_crypto(self, ticker: str) -> pl.DataFrame:
        """Fetch BTCUSDT from Binance free tier."""
        import requests
        try:
            # Just get the latest price for simplicity, or klines for history
            # The prompt says: Binance public REST https://api.binance.com/api/v3/ticker/price?symbol=BTCUSDT
            # And funding rate: https://fapi.binance.com/fapi/v1/fundingRate
            # Since we need history for PricesRaw, we use klines
            res = requests.get("https://api.binance.com/api/v3/klines?symbol=BTCUSDT&interval=1d&limit=30", timeout=10)
            if res.status_code == 200:
                data = res.json()
                records = []
                for row in data:
                    records.append({
                        "Date": datetime.fromtimestamp(row[0]/1000, tz=timezone.utc),
                        "Open": float(row[1]),
                        "High": float(row[2]),
                        "Low": float(row[3]),
                        "Close": float(row[4]),
                        "Adj Close": float(row[4]),
                        "Volume": float(row[5]),
                        "Dividends": 0.0,
                        "Stock Splits": 0.0,
                    })
                df = pl.DataFrame(records)
                return df
        except Exception as e:
            logger.warning(f"Binance fetch failed: {e}")
        return pl.DataFrame()

    async def _download_symbol(self, ticker: str) -> pl.DataFrame:
        if ticker == "BTC-USD" or ticker == "BTCUSDT":
            df = await asyncio.to_thread(self._download_binance_crypto, ticker)
            return self._to_polars(df.to_pandas() if not df.is_empty() else None, ticker)
            
        start_date = datetime.now(timezone.utc).date() - timedelta(days=365 * YEARS_OF_HISTORY + 10)
        end_date = datetime.now(timezone.utc).date() + timedelta(days=1)

        try:
            raw_data = await asyncio.to_thread(
                yf.download,
                tickers=ticker,
                start=start_date.isoformat(),
                end=end_date.isoformat(),
                interval=DEFAULT_INTERVAL,
                auto_adjust=False,
                progress=False,
                group_by="column",
                threads=True,
                actions=True,
            )
            df = self._to_polars(raw_data, ticker)
            if not df.is_empty():
                return df
        except Exception as e:
            logger.warning(f"yfinance failed for {ticker}: {e}")
            
        # Fallback to nsepython
        if ticker.endswith(".NS"):
            base_sym = ticker.replace(".NS", "")
            try:
                import requests
                from nsepython import nse_eq
                payload = nse_eq(base_sym)
                # Parse single latest quote if historical fails
                if payload and 'priceInfo' in payload:
                    pi = payload['priceInfo']
                    records = [{
                        "Date": datetime.now(timezone.utc),
                        "Open": pi.get("open", 0),
                        "High": pi.get("intraDayHighLow", {}).get("max", 0),
                        "Low": pi.get("intraDayHighLow", {}).get("min", 0),
                        "Close": pi.get("close", 0),
                        "Adj Close": pi.get("close", 0),
                        "Volume": payload.get('preOpenMarket', {}).get('totalTradedVolume', 0),
                        "Dividends": 0.0,
                        "Stock Splits": 0.0
                    }]
                    return self._to_polars(pl.DataFrame(records).to_pandas(), ticker)
            except Exception as e:
                logger.warning(f"nsepython fallback failed for {ticker}: {e}")

        return self._to_polars(None, ticker)

    def _to_polars(self, raw_data: Any, ticker: str) -> pl.DataFrame:
        if raw_data is None or getattr(raw_data, "empty", True):
            return pl.DataFrame(
                schema={
                    "date": pl.Date,
                    "open": pl.Float64,
                    "high": pl.Float64,
                    "low": pl.Float64,
                    "close": pl.Float64,
                    "adj_close": pl.Float64,
                    "volume": pl.Int64,
                    "vwap": pl.Float64,
                    "dividends": pl.Float64,
                    "stock_splits": pl.Float64,
                }
            )

        if hasattr(raw_data.columns, "nlevels") and raw_data.columns.nlevels > 1:
            raw_data = raw_data.copy()
            raw_data.columns = raw_data.columns.get_level_values(0)

        frame = pl.from_pandas(raw_data.reset_index()) if hasattr(raw_data, "reset_index") else raw_data

        if "Date" not in frame.columns and "Datetime" in frame.columns:
            frame = frame.rename({"Datetime": "Date"})

        rename_map = {
            "Date": "date",
            "Open": "open",
            "High": "high",
            "Low": "low",
            "Close": "close",
            "Adj Close": "adj_close",
            "Volume": "volume",
            "Dividends": "dividends",
            "Stock Splits": "stock_splits",
        }
        frame = frame.rename({column: target for column, target in rename_map.items() if column in frame.columns})

        if "adj_close" not in frame.columns:
            frame = frame.with_columns(pl.col("close").alias("adj_close"))
        if "dividends" not in frame.columns:
            frame = frame.with_columns(pl.lit(0.0, dtype=pl.Float64).alias("dividends"))
        if "stock_splits" not in frame.columns:
            frame = frame.with_columns(pl.lit(0.0, dtype=pl.Float64).alias("stock_splits"))

        typical_price = (pl.col("high").cast(pl.Float64) + pl.col("low").cast(pl.Float64) + pl.col("close").cast(pl.Float64)) / 3.0
        pv = typical_price * pl.col("volume").cast(pl.Float64)
        cum_pv = pv.cum_sum()
        cum_vol = pl.col("volume").cast(pl.Float64).cum_sum()
        vwap_expr = (
            pl.when(cum_vol > 0.0)
            .then(cum_pv / cum_vol)
            .otherwise(None)
            .alias("vwap")
        )
        frame = frame.with_columns(vwap_expr)

        cleaned = (
            frame.select(["date", "open", "high", "low", "close", "adj_close", "volume", "vwap", "dividends", "stock_splits"])
            .with_columns(
                pl.col("date").cast(pl.Date),
                pl.col(["open", "high", "low", "close", "adj_close", "vwap", "dividends", "stock_splits"]).cast(pl.Float64),
                pl.col("volume").cast(pl.Int64),
            )
            .sort("date")
            .fill_null(strategy="forward")
        )

        return cleaned.filter(pl.col("date").is_not_null())

    def _persist_daily_price_data(self, results: list[FetchResult]) -> None:
        self.db_manager.create_tables()

        with self.db_manager.session_scope() as session:
            for result in results:
                for row in result.frame.iter_rows(named=True):
                    raw_payload = self._build_daily_payload(result.symbol, row)
                    statement_raw = sqlite_insert(PricesRaw).values(raw_payload)
                    statement_raw = statement_raw.on_conflict_do_update(
                        index_elements=["Symbol", "Date"],
                        set_={
                            "Open": statement_raw.excluded["Open"],
                            "High": statement_raw.excluded["High"],
                            "Low": statement_raw.excluded["Low"],
                            "Close": statement_raw.excluded["Close"],
                            "AdjClose": statement_raw.excluded["AdjClose"],
                            "Volume": statement_raw.excluded["Volume"],
                            "VWAP": statement_raw.excluded["VWAP"],
                        },
                    )
                    session.execute(statement_raw)

                    daily_payload = raw_payload.copy()
                    statement_daily = sqlite_insert(DailyPriceData).values(daily_payload)
                    statement_daily = statement_daily.on_conflict_do_update(
                        index_elements=["Symbol", "Date"],
                        set_={
                            "Open": statement_daily.excluded["Open"],
                            "High": statement_daily.excluded["High"],
                            "Low": statement_daily.excluded["Low"],
                            "Close": statement_daily.excluded["Close"],
                            "AdjClose": statement_daily.excluded["AdjClose"],
                            "Volume": statement_daily.excluded["Volume"],
                            "VWAP": statement_daily.excluded["VWAP"],
                        },
                    )
                    session.execute(statement_daily)

                    div_val = self._to_float(row.get("dividends"))
                    if div_val and div_val > 0.0:
                        div_stmt = sqlite_insert(CorporateActions).values({
                            "Symbol": result.symbol,
                            "Date": self._to_python_date(row["date"]),
                            "ActionType": "DIVIDEND",
                            "Value": div_val,
                        })
                        div_stmt = div_stmt.on_conflict_do_update(
                            index_elements=["Symbol", "Date", "ActionType"],
                            set_={"Value": div_stmt.excluded["Value"]},
                        )
                        session.execute(div_stmt)

                    split_val = self._to_float(row.get("stock_splits"))
                    if split_val and split_val > 0.0:
                        split_stmt = sqlite_insert(CorporateActions).values({
                            "Symbol": result.symbol,
                            "Date": self._to_python_date(row["date"]),
                            "ActionType": "SPLIT",
                            "Value": split_val,
                        })
                        split_stmt = split_stmt.on_conflict_do_update(
                            index_elements=["Symbol", "Date", "ActionType"],
                            set_={"Value": split_stmt.excluded["Value"]},
                        )
                        session.execute(split_stmt)

    async def _fetch_macro_regime_data(self) -> list[FetchResult]:
        # FRED data overrides
        from nexus_astra.config import config
        fred_key = config.get_secret("FRED_API_KEY")
        
        frames = []
        if fred_key:
            try:
                from fredapi import Fred
                fred = Fred(api_key=fred_key)
                
                def fetch_fred(series_id, metric_name):
                    try:
                        s = fred.get_series(series_id)
                        df = pl.DataFrame({
                            "date": s.index,
                            metric_name: s.values
                        })
                        # Clean up NaNs
                        return df.filter(pl.col(metric_name).is_not_nan()).with_columns(pl.col("date").cast(pl.Date))
                    except Exception as e:
                        logger.warning(f"FRED fetch failed for {series_id}: {e}")
                        return pl.DataFrame(schema={"date": pl.Date, metric_name: pl.Float64})

                dxy = await asyncio.to_thread(fetch_fred, "DTWEXBGS", "dxy")
                us10y = await asyncio.to_thread(fetch_fred, "DGS10", "us10y")
                crude = await asyncio.to_thread(fetch_fred, "DCOILWTICO", "brent_crude")
                gold = await asyncio.to_thread(fetch_fred, "IDTCOGSR", "gold")
                usdinr = await asyncio.to_thread(fetch_fred, "DEXINUS", "usd_inr")
                
                # We can store them as dummy symbols to merge later
                frames.append(FetchResult("DXY", dxy))
                frames.append(FetchResult("US10Y", us10y))
                frames.append(FetchResult("CRUDE", crude))
                frames.append(FetchResult("GOLD", gold))
                frames.append(FetchResult("INR=X", usdinr))
                
            except Exception as e:
                logger.warning(f"FRED initialization failed. SKIP. {e}")
        else:
            logger.info("FRED_API_KEY missing. SKIP FRED macro data.")
            
        # Standard yf macro tickers
        tasks = [self._download_symbol(symbol) for symbol in MACRO_TICKERS]
        downloaded = await asyncio.gather(*tasks)
        for symbol, frame in zip(MACRO_TICKERS, downloaded, strict=True):
            frames.append(FetchResult(symbol, frame))
            
        return frames

    def _persist_macro_regime_data(self, results: list[FetchResult]) -> None:
        self.db_manager.create_tables()

        frame_map = {result.symbol: result.frame for result in results}
        unified_frame = self._merge_macro_frames(frame_map)

        with self.db_manager.session_scope() as session:
            for row in unified_frame.iter_rows(named=True):
                payload = {
                    "Date": row["date"],
                    "India_VIX": row.get("india_vix"),
                    "US_VIX": row.get("us_vix"),
                    "USD_INR": row.get("usd_inr"),
                    "Brent_Crude": row.get("brent_crude"),
                }
                statement = sqlite_insert(MacroRegime).values(payload)
                statement = statement.on_conflict_do_update(
                    index_elements=["Date"],
                    set_={
                        "India_VIX": statement.excluded["India_VIX"],
                        "US_VIX": statement.excluded["US_VIX"],
                        "USD_INR": statement.excluded["USD_INR"],
                        "Brent_Crude": statement.excluded["Brent_Crude"],
                    },
                )
                session.execute(statement)

    def _build_daily_payload(self, symbol: str, row: dict[str, Any]) -> dict[str, Any]:
        # Normalize: strip .NS suffix – DB stores clean symbols (RELIANCE, ^NSEI, BTC-USD)
        clean_sym = symbol.removesuffix(".NS")
        return {
            "Symbol": clean_sym,
            "Date": self._to_python_date(row["date"]),
            "Open": self._to_float(row["open"]),
            "High": self._to_float(row["high"]),
            "Low": self._to_float(row["low"]),
            "Close": self._to_float(row["close"]),
            "AdjClose": self._to_float(row.get("adj_close", row["close"])),
            "Volume": self._to_int(row["volume"]),
            "VWAP": self._to_float(row.get("vwap")),
        }

    def _merge_macro_frames(self, frame_map: dict[str, pl.DataFrame]) -> pl.DataFrame:
        india_vix = self._rename_with_suffix(frame_map.get("^INDIAVIX", pl.DataFrame()), "india_vix")
        usd_inr = frame_map.get("INR=X", pl.DataFrame())
        if usd_inr.is_empty():
            usd_inr = pl.DataFrame(schema={"date": pl.Date, "usd_inr": pl.Float64})
        elif "usd_inr" not in usd_inr.columns:
            usd_inr = self._rename_with_suffix(usd_inr, "usd_inr")

        merged = india_vix.join(usd_inr, on="date", how="full", coalesce=True)
        
        crude = frame_map.get("CRUDE", pl.DataFrame())
        if not crude.is_empty():
            merged = merged.join(crude, on="date", how="full", coalesce=True)
            
        us_vix = self._rename_with_suffix(frame_map.get("^VIX", pl.DataFrame()), "us_vix")
        if not us_vix.is_empty():
            merged = merged.join(us_vix, on="date", how="full", coalesce=True)

        if "india_vix" not in merged.columns:
            merged = merged.with_columns(pl.lit(None, dtype=pl.Float64).alias("india_vix"))
        if "usd_inr" not in merged.columns:
            merged = merged.with_columns(pl.lit(None, dtype=pl.Float64).alias("usd_inr"))
        if "us_vix" not in merged.columns:
            merged = merged.with_columns(pl.lit(None, dtype=pl.Float64).alias("us_vix"))
        if "brent_crude" not in merged.columns:
            merged = merged.with_columns(pl.lit(None, dtype=pl.Float64).alias("brent_crude"))

        return (
            merged.select(["date", "india_vix", "us_vix", "usd_inr", "brent_crude"])
            .sort("date")
            .fill_null(strategy="forward")
        )

    def _rename_with_suffix(self, frame: pl.DataFrame, metric_name: str) -> pl.DataFrame:
        if frame.is_empty():
            return pl.DataFrame(schema={"date": pl.Date, metric_name: pl.Float64})

        value_column = "close" if "close" in frame.columns else frame.columns[-1]
        return (
            frame.select(["date", value_column])
            .rename({value_column: metric_name})
            .sort("date")
            .fill_null(strategy="forward")
        )

    @staticmethod
    def _to_python_date(value: Any) -> date:
        if isinstance(value, date) and not isinstance(value, datetime):
            return value
        if isinstance(value, datetime):
            return value.date()
        return pl.Series([value]).cast(pl.Date)[0]

    @staticmethod
    def _to_float(value: Any) -> float | None:
        if value is None:
            return None
        if hasattr(value, "item"):
            value = value.item()
        if value != value:
            return None
        return float(value)

    @staticmethod
    def _to_int(value: Any) -> int:
        if value is None:
            return 0
        if hasattr(value, "item"):
            value = value.item()
        if value != value:
            return 0
        return int(value)

async def main() -> None:
    fetcher = MarketDataFetcher()
    await fetcher.fetch_all()

if __name__ == "__main__":
    asyncio.run(main())
