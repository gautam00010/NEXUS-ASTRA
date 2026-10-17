"""OpenAlgo Data Fetcher for live NSE/BSE Market Data."""

from __future__ import annotations

import logging
from typing import Any

from nexus_astra.config import config

logger = logging.getLogger(__name__)

try:
    from openalgo import api as openalgo_api
except ImportError:
    try:
        from openalgo import openalgo as openalgo_api
    except ImportError:
        openalgo_api = None


class OpenAlgoFetcher:
    def __init__(self) -> None:
        self.api_key = config.get_secret("OPENALGO_API_KEY") or "mock_key"
        self.host = config.get_secret("OPENALGO_HOST") or "http://127.0.0.1:5000"
        self.client = None
        if openalgo_api is not None:
            try:
                self.client = openalgo_api(api_key=self.api_key, host=self.host)
            except Exception as e:
                logger.debug(f"OpenAlgo client init warning: {e}")

    def fetch_live_price(self, symbol: str) -> float | None:
        """
        Fetches live NSE data via OpenAlgo bridge.
        Includes backoff retries.
        """
        if self.client is None:
            return None

        for delay in (2, 4, 8):
            try:
                if hasattr(self.client, "get_ltp"):
                    res = self.client.get_ltp(symbol=symbol)
                elif hasattr(self.client, "ltp"):
                    res = self.client.ltp(symbol=symbol)
                else:
                    res = None

                if res and isinstance(res, dict) and "ltp" in res:
                    return float(res["ltp"])
            except Exception as e:
                logger.warning(f"OpenAlgo fetch failed: {e}. Retrying in {delay}s...")
                import time
                time.sleep(delay)

        logger.error("OpenAlgo fetch exhausted retries - DATA_FAIL")
        return None
