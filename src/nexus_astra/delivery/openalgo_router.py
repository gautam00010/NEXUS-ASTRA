"""OpenAlgo Unified Indian Broker Router."""
import logging
from openalgo import api
from nexus_astra.config import config

logger = logging.getLogger(__name__)

class OpenAlgoRouter:
    def __init__(self):
        self.api_key = config.get_secret("OPENALGO_API_KEY") or "mock_key"
        self.host = config.get_secret("OPENALGO_HOST") or "http://127.0.0.1:5000"
        self.client = api(api_key=self.api_key, host=self.host)
        
    def dispatch_signal(self, symbol: str, signal_type: str, strategy: str = "NEXUS-ASTRA") -> bool:
        """
        Routes algorithmic signals to Indian brokers via OpenAlgo.
        Provides a seamless bridge to executing live trades.
        """
        try:
            # Map signal types to openalgo actions
            action = "BUY" if "BUY" in signal_type.upper() else "SELL"
            
            # Place order via OpenAlgo API
            res = self.client.place_order(
                strategy=strategy,
                symbol=symbol,
                action=action
            )
            
            logger.info(f"OpenAlgo dispatched {action} for {symbol}: {res}")
            return True
        except Exception as e:
            logger.warning(f"OpenAlgo routing skipped/failed: {e}")
            return False
