"""OpenAlgo Data Fetcher for live NSE/BSE Market Data."""
import logging
from openalgo import api
from nexus_astra.config import config

logger = logging.getLogger(__name__)

class OpenAlgoFetcher:
    def __init__(self):
        self.api_key = config.get_secret("OPENALGO_API_KEY") or "mock_key"
        self.host = config.get_secret("OPENALGO_HOST") or "http://127.0.0.1:5000"
        self.client = api(api_key=self.api_key, host=self.host)
        
    def fetch_live_price(self, symbol: str) -> float | None:
        """
        Fetches live NSE data via OpenAlgo bridge.
        Includes backoff retries.
        """
        for delay in (2, 4, 8):
            try:
                # Use OpenAlgo's get_ltp (last traded price) or similar
                # Assuming generic API structure since openalgo is a local bridge
                res = self.client.get_ltp(symbol=symbol)
                if res and 'ltp' in res:
                    return float(res['ltp'])
            except Exception as e:
                logger.warning(f"OpenAlgo fetch failed: {e}. Retrying in {delay}s...")
                import time; time.sleep(delay)
                
        logger.error("OpenAlgo fetch exhausted retries - DATA_FAIL")
        return None
