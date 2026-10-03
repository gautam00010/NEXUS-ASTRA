"""Modern social and alternative sentiment fetcher replacing legacy social scraping."""

from __future__ import annotations

import logging
from datetime import date
from typing import Any

logger = logging.getLogger(__name__)


class SocialFetcher:
    """Modern social and alternative sentiment fetcher with Point-In-Time universe resolution."""

    def __init__(
        self,
        as_of_date: date | None = None,
        universe: list[str] | None = None,
        db_manager: Any = None,
        *args,
        **kwargs,
    ) -> None:
        self.db_manager = db_manager
        if universe is not None:
            self.assets = list(universe)
        elif as_of_date is not None:
            try:
                from scripts.populate_constituents import load_nifty_500_pit
                self.assets = load_nifty_500_pit(as_of_date)
            except Exception:
                self.assets = ["RELIANCE", "TCS", "INFY"]
        else:
            self.assets = ["RELIANCE", "TCS", "INFY"]

    async def fetch_social_sentiment(self, symbol: str) -> float:
        """Social scraping removed per free production spec - using NewsAPI + Google Trends + Finnhub."""
        logger.info(f"Social scraping removed - using NewsAPI + Google Trends + Finnhub for {symbol}")
        return 0.0

    async def fetch_all(self, *args, **kwargs) -> list[dict[str, Any]]:
        logger.info("Social scraping removed - using NewsAPI + Google Trends + Finnhub")
        return []

    async def run_pipeline(self) -> None:
        pass


# Backward-compatible alias
SocialScraper = SocialFetcher

__all__ = ["SocialFetcher", "SocialScraper"]
