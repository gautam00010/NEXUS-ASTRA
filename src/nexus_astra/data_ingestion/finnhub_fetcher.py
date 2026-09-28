"""Finnhub fetcher for market news and insights."""
import logging
import asyncio
from typing import Any

logger = logging.getLogger(__name__)

class FinnhubFetcher:
    def __init__(self):
        from nexus_astra.config import config
        self.api_key = config.get_secret("FINNHUB_API_KEY")
        self.client = None
        
        if self.api_key:
            try:
                import finnhub
                self.client = finnhub.Client(api_key=self.api_key)
            except ImportError:
                logger.warning("finnhub-python not installed")

    async def get_news(self, category: str = "general") -> list[dict[str, Any]]:
        if not self.client:
            logger.info("FINNHUB_API_KEY missing. SKIP finnhub news.")
            return []
            
        try:
            return await asyncio.to_thread(self.client.general_news, category, min_id=0)
        except Exception as e:
            logger.warning(f"Finnhub news failed: {e}")
            return []
            
    async def get_insider(self, symbol: str) -> list[dict[str, Any]]:
        if not self.client:
            logger.info("FINNHUB_API_KEY missing. SKIP finnhub insider.")
            return []
            
        try:
            return await asyncio.to_thread(self.client.insider_transactions, symbol)
        except Exception as e:
            logger.warning(f"Finnhub insider failed for {symbol}: {e}")
            return []


class USMarketFetcher:
    """Fetch US market data for cross-asset influence on Indian markets.
    Uses Finnhub (if key present) and FRED (if key present) free tiers.
    Stores in macro_overlay with PIT timestamps.
    Single responsibility: US data only.
    """

    FRED_SERIES = {
        "dxy": "DTWEXBGS",
        "us10y": "DGS10",
        "crude": "DCOILWTICO",
        "gold": "GOLDAMGBD228NLBM",
    }
    FINNHUB_SYMBOLS = {
        "spx": "^GSPC",
        "nasdaq": "^IXIC",
        "vix": "^VIX",
    }

    def __init__(self) -> None:
        from nexus_astra.config import config
        self._finnhub_key = config.get_secret("FINNHUB_API_KEY")
        self._fred_key = config.get_secret("FRED_API_KEY")
        self._client = None
        if self._finnhub_key:
            try:
                import finnhub
                self._client = finnhub.Client(api_key=self._finnhub_key)
            except ImportError:
                logger.warning("finnhub-python not installed – US equity skipped")

    async def fetch_us_snapshot(self) -> dict[str, float | None]:
        """
        Returns a snapshot dict with keys:
          spx_close, spx_pct_chg, nasdaq_close, vix_close,
          dxy, us10y, crude, gold
        Any value that cannot be fetched returns None (never random, never 0.0 mock).
        """
        results: dict[str, float | None] = {}

        # --- Finnhub equity quotes (SPX, Nasdaq, VIX) ---
        if self._client:
            for label, sym in self.FINNHUB_SYMBOLS.items():
                results[label + "_close"] = await self._fetch_finnhub_quote(sym)
            # SPX % change = (close - prev_close) / prev_close
            spx_c = results.get("spx_close")
            spx_p = await self._fetch_finnhub_prev_close("^GSPC")
            if spx_c is not None and spx_p and spx_p != 0:
                results["spx_pct_chg"] = (spx_c - spx_p) / spx_p * 100.0
            else:
                results["spx_pct_chg"] = None
        else:
            logger.info("FINNHUB_API_KEY missing – SKIP US equity quotes")
            for label in self.FINNHUB_SYMBOLS:
                results[label + "_close"] = None
            results["spx_pct_chg"] = None

        # --- FRED macro (DXY, US10Y, Crude, Gold) ---
        if self._fred_key:
            fred_data = await asyncio.to_thread(self._fetch_fred_batch)
            results.update(fred_data)
        else:
            logger.info("FRED_API_KEY missing – SKIP DXY/US10Y/Crude/Gold")
            for k in self.FRED_SERIES:
                results[k] = None

        return results

    async def _fetch_finnhub_quote(self, symbol: str) -> float | None:
        """Fetch latest close with exponential backoff 2s,4s,8s – returns None on fail."""
        for delay in (2, 4, 8):
            try:
                q = await asyncio.to_thread(self._client.quote, symbol)
                return float(q["c"]) if q and q.get("c") else None
            except Exception as exc:
                logger.warning(f"Finnhub quote {symbol} failed: {exc}. Retry in {delay}s")
                await asyncio.sleep(delay)
        logger.error(f"Finnhub quote {symbol} exhausted retries – DATA_FAIL")
        return None

    async def _fetch_finnhub_prev_close(self, symbol: str) -> float | None:
        """Fetch previous close for pct-change calculation."""
        try:
            q = await asyncio.to_thread(self._client.quote, symbol)
            return float(q["pc"]) if q and q.get("pc") else None
        except Exception as exc:
            logger.warning(f"Finnhub prev_close {symbol} failed: {exc}")
            return None

    def _fetch_fred_batch(self) -> dict[str, float | None]:
        """Synchronous FRED batch fetch – call via asyncio.to_thread."""
        out: dict[str, float | None] = {}
        try:
            from fredapi import Fred
            fred = Fred(api_key=self._fred_key)
            for label, series_id in self.FRED_SERIES.items():
                for delay in (2, 4, 8):
                    try:
                        s = fred.get_series(series_id)
                        val = float(s.dropna().iloc[-1]) if not s.dropna().empty else None
                        out[label] = val
                        break
                    except Exception as exc:
                        logger.warning(f"FRED {series_id} failed: {exc}. Retry in {delay}s")
                        import time; time.sleep(delay)
                else:
                    logger.error(f"FRED {series_id} exhausted retries – DATA_FAIL")
                    out[label] = None
        except ImportError:
            logger.warning("fredapi not installed – SKIP FRED")
            for k in self.FRED_SERIES:
                out[k] = None
        except Exception as exc:
            logger.error(f"FRED batch fetch failed: {exc}")
            for k in self.FRED_SERIES:
                out[k] = None
        return out
