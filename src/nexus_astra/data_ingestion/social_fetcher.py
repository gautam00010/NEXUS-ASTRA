"""Modern social and alternative sentiment fetcher.

Replaces legacy reddit/praw scraping with a clean async fetcher.
Uses NewsAPI (free) for headlines + VADER sentiment.
No praw dependency. SocialScraper is an alias for backward compatibility.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)


class SocialFetcher:
    """Modern social and alternative sentiment fetcher with Point-In-Time universe resolution.

    Fetches news sentiment via NewsAPI (free tier, if key present).
    Falls back to neutral 0.0 sentiment when API unavailable.
    No praw / reddit dependency — removed as garbage per audit spec.
    """

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
                logger.warning("SocialFetcher: PIT universe unavailable – using ^NSEI + BTC-USD")
                self.assets = ["^NSEI", "BTC-USD"]
        else:
            self.assets = ["^NSEI", "BTC-USD"]

        from nexus_astra.config import config
        self._news_key = config.get_secret("NEWS_API_KEY")

    async def _fetch_reddit_posts_and_comments(self) -> list[dict]:
        """Stub retained for test-mock compatibility. Returns empty list in production.

        Tests override this method with mock data. Production uses NewsAPI instead.
        """
        logger.info("SocialFetcher: reddit fetch stub called (no praw dependency)")
        return []

    async def fetch_social_sentiment(self, symbol: str) -> dict[str, float]:
        """Fetch social sentiment for a symbol. Uses NewsAPI if key present, else returns neutral."""
        try:
            if self._news_key:
                return await asyncio.to_thread(self._fetch_newsapi_sentiment, symbol)
            else:
                logger.info(f"NEWS_API_KEY missing – returning neutral sentiment for {symbol}")
                return {"sentiment_score": 0.0, "source": "neutral_fallback", "headlines": 0}
        except Exception as exc:
            logger.warning(f"SocialFetcher sentiment fetch failed for {symbol}: {exc}")
            return {"sentiment_score": 0.0, "source": "error_fallback", "headlines": 0}

    def _fetch_newsapi_sentiment(self, symbol: str) -> dict[str, float]:
        """Synchronous NewsAPI + VADER sentiment. Called via asyncio.to_thread."""
        try:
            import requests
            query = symbol.replace(".NS", "").replace("^", "")
            url = (
                f"https://newsapi.org/v2/everything?q={query}"
                f"&language=en&sortBy=publishedAt&pageSize=10"
                f"&apiKey={self._news_key}"
            )
            resp = requests.get(url, timeout=10)
            resp.raise_for_status()
            articles = resp.json().get("articles", [])
            if not articles:
                return {"sentiment_score": 0.0, "source": "newsapi_no_results", "headlines": 0}

            try:
                from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
                sia = SentimentIntensityAnalyzer()
                scores = []
                for art in articles:
                    text = (art.get("title") or "") + " " + (art.get("description") or "")
                    if text.strip():
                        scores.append(sia.polarity_scores(text)["compound"])
                avg = sum(scores) / len(scores) if scores else 0.0
                return {"sentiment_score": round(avg, 4), "source": "newsapi_vader", "headlines": len(articles)}
            except ImportError:
                # VADER not installed — return neutral
                return {"sentiment_score": 0.0, "source": "newsapi_no_vader", "headlines": len(articles)}

        except Exception as exc:
            logger.warning(f"NewsAPI fetch failed: {exc}")
            return {"sentiment_score": 0.0, "source": "newsapi_error", "headlines": 0}

    async def run(self) -> dict[str, Any]:
        """Run sentiment fetch for entire universe."""
        results = {}
        for sym in self.assets:
            results[sym] = await self.fetch_social_sentiment(sym)
        return results


# Backward-compatibility alias – tests import SocialScraper
SocialScraper = SocialFetcher
