"""Zerodha API fetcher stub."""
import logging

logger = logging.getLogger(__name__)

class ZerodhaFetcher:
    def __init__(self):
        from nexus_astra.config import config
        self.api_key = config.get_secret("ZERODHA_API_KEY")
        self.secret = config.get_secret("ZERODHA_SECRET")
        
        if not self.api_key or not self.secret:
            logger.info("Zerodha skip - using yfinance free")
            
    async def fetch_portfolio(self):
        return []
