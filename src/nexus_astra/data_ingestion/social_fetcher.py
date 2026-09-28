"""Wrapper to replace deprecated social fetching with NewsAPI/Google Trends."""

import logging
from typing import Any

logger = logging.getLogger(__name__)

class SocialFetcher:
    """Mock/Replacement for previous social API integration."""
    
    def __init__(self, *args, **kwargs):
        pass

    async def fetch_social_sentiment(self, symbol: str) -> float:
        """Social removed - using NewsAPI + Google Trends + Finnhub news."""
        logger.info(f"Social removed - using NewsAPI + Google Trends + Finnhub news for {symbol}")
        return 0.0

    async def fetch_all(self, *args, **kwargs) -> list[dict[str, Any]]:
        logger.info("Social removed - using NewsAPI + Google Trends + Finnhub news")
        return []
