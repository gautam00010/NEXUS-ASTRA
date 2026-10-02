"""Indian financial news sentiment engine using NewsAPI, Hugging Face transformers, VADER, and Polars."""

from __future__ import annotations
from nexus_astra.agents.von_router import VonRouter

import json
import logging
import os
from datetime import datetime, timezone, date, timedelta
from typing import Any

import polars as pl
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from nexus_astra.data_ingestion.database import NewsSentimentCache, DailyPriceData, DatabaseManager, database_manager

logger = logging.getLogger(__name__)

NEWS_API_KEY_ENV = "NEWS_API_KEY"

CREDIBILITY_WEIGHTS = {
    "reuters": 1.0,
    "bloomberg": 1.0,
    "the economic times": 0.9,
    "livemint": 0.9,
    "moneycontrol": 0.8,
    "ndtv": 0.7,
    "republic world": 0.5,
}


class NewsSentiment:
    """Analyze and cache Indian market news headlines sentiment using Transformers/VADER."""

    def __init__(self, db_manager: DatabaseManager | None = None, api_key: str | None = None) -> None:
        from nexus_astra.config import config
        self.db_manager = db_manager or database_manager
        self.api_key = api_key or config.get_secret("NEWS_API_KEY")
        self.news_url = "https://newsapi.org/v2/everything"
        self._classifier = None

    def _get_classifier(self) -> Any:
        """Lazily initialize the Hugging Face transformers pipeline."""
        if self._classifier is None:
            from transformers import pipeline
            self._classifier = pipeline(
                "sentiment-analysis",
                model="distilbert-base-uncased-finetuned-sst-2-english",
            )
        return self._classifier

    async def run_pipeline(self, trends_z: float|str = None, finnhub_news: list = None, edgar_filings: list = None, fred_macro: dict = None) -> dict[str, Any]:
        """Fetch, analyze, cache, and return today's news sentiment metrics."""
        self.db_manager.create_tables()
        today = datetime.now(timezone.utc).date()

        # 1. Check cache first
        cached_record = self._get_cached_sentiment(today)
        if cached_record:
            logger.info("Found cached news sentiment in database.")
            return cached_record

        # 2. Fetch news
        headlines = await self._fetch_news()
        
        # Combine inputs for VON
        combined_text = f"NewsAPI: {len(headlines)} headlines. "
        if trends_z is not None and trends_z != "DATA_FAIL":
            combined_text += f"Google Trends Z-Score: {trends_z:.2f}. "
        if finnhub_news:
            combined_text += f"Finnhub: {len(finnhub_news)} articles. "
        if edgar_filings:
            combined_text += f"SEC EDGAR: {len(edgar_filings)} filings. "
        if fred_macro:
            combined_text += f"FRED Macro: {fred_macro}. "

        # Use VON on combined state
        router = VonRouter()
        von_res = router.system_one(combined_text, ["news_tone", "event_risk", "regime_state"])

        # 3. Compute sentiment scores (Legacy method for backwards compatibility or fine-grained headline score)
        analyzed_headlines = self._classify_sentiment(headlines)

        # 4. Aggregate daily sentiment score using Polars
        daily_score = self._aggregate_sentiment(analyzed_headlines)
        
        # Override with VON if available
        news_tone_data = von_res.get("answers", {}).get("news_tone", {})
        if isinstance(news_tone_data, dict) and news_tone_data.get("status") != "DATA_FAIL":
            von_score = news_tone_data.get("score", 0.0)
            daily_score = (daily_score * 0.5) + (von_score * 0.5)

        # 5. Check sentiment divergence
        flags = self._detect_sentiment_divergence(daily_score)

        # 6. Save to cache
        result = {
            "Date": today,
            "Daily_Sentiment_Score": daily_score,
            "Raw_Headlines_JSON": json.dumps({"von_combined": von_res, "headlines": analyzed_headlines}),
            "Flags": flags,
        }
        self._save_to_cache(result)
        return result

    def _get_cached_sentiment(self, target_date: date) -> dict[str, Any] | None:
        """Query database cache for existing sentiment records of the target date."""
        with self.db_manager.session_scope() as session:
            row = session.query(NewsSentimentCache).filter(NewsSentimentCache.date == target_date).first()
            if row:
                return {
                    "Date": row.date,
                    "Daily_Sentiment_Score": float(row.daily_sentiment_score),
                    "Raw_Headlines_JSON": row.raw_headlines_json,
                    "Flags": row.flags,
                }
        return None

    async def _fetch_news(self) -> list[dict[str, Any]]:
        """Fetch headlines containing market keywords in last 24h from NewsAPI."""
        if not self.api_key:
            logger.warning("NewsAPI key is missing. Skipping news fetch.")
            return []

        import aiohttp
        now = datetime.now(timezone.utc)
        from_time = (now - timedelta(hours=72)).strftime("%Y-%m-%d")
        
        params = {
            "q": "Nifty OR Sensex OR RBI OR \"Indian economy\" OR \"stock market\"",
            "from": from_time,
            "sortBy": "publishedAt",
            "pageSize": 50,
            "language": "en",
            "apiKey": self.api_key,
        }


        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(self.news_url, params=params, timeout=15) as r:
                    r.raise_for_status()
                    data = await r.json()
                    articles = data.get("articles", [])
                    
                    headlines = []
                    for art in articles:
                        headlines.append({
                            "title": art.get("title", ""),
                            "source": art.get("source", {}).get("name", "Unknown").lower()
                        })
                    return headlines
        except Exception as e:
            logger.error(f"Failed to fetch NewsAPI headlines: {e}. Skipping news fetch.")
            return []

    def _classify_sentiment(self, headlines: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Score sentiment with VON (0.9) and VADER (0.1)."""
        results = []
        router = VonRouter()
        
        from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
        vader = SentimentIntensityAnalyzer()
        
        for h in headlines:
            title = h["title"]
            source = h["source"]
            state = f"Headline: {title} | Source: {source}"
            
            # VON Score using system_one for all questions
            von_res = router.system_one(state, ["regime_state", "event_risk", "news_tone", "fii_exhaustion", "promoter_signal"])
            news_tone_data = von_res.get("answers", {}).get("news_tone", {})
            von_score = news_tone_data.get("score", 0.0) if isinstance(news_tone_data, dict) else 0.0
            
            if news_tone_data.get("status") == "DATA_FAIL":
                von_score = 0.0
                
            # VADER Score
            vader_res = vader.polarity_scores(title)
            vader_score = vader_res["compound"]
            
            # Weighted Combine
            final_val = (von_score * 0.9) + (vader_score * 0.1)
            
            if final_val > 0.05:
                tone = "bullish"
            elif final_val < -0.05:
                tone = "bearish"
            else:
                tone = "neutral"
                
            results.append({
                "title": title,
                "source": source,
                "sentiment": tone,
                "confidence": abs(final_val),
                "val": final_val,
                "von_metadata": von_res
            })
        return results


    def _aggregate_sentiment(self, analyzed_headlines: list[dict[str, Any]]) -> float:
        """Aggregate daily sentiment score weighted by source credibility using pure Polars."""
        if not analyzed_headlines:
            return 0.0

        # Build Polars DataFrame
        records = []
        for h in analyzed_headlines:
            source = h["source"]
            weight = CREDIBILITY_WEIGHTS.get(source, 0.5)
            records.append({
                "val": h["val"],
                "confidence": h["confidence"],
                "source_weight": weight
            })
            
        df = pl.DataFrame(records)
        df = df.with_columns(
            (pl.col("val") * pl.col("confidence") * pl.col("source_weight")).alias("weighted_score"),
            (pl.col("confidence") * pl.col("source_weight")).alias("weight")
        )
        
        total_weight = df.select(pl.col("weight").sum()).item() or 1.0
        total_score = df.select(pl.col("weighted_score").sum()).item() or 0.0
        
        daily_score = total_score / total_weight
        return float(max(-1.0, min(1.0, daily_score)))

    def _detect_sentiment_divergence(self, daily_score: float) -> str | None:
        """Flag SENTIMENT_DIVERGENCE if sentiment <= -0.8 but Nifty holds above 20-day EMA."""
        if daily_score > -0.8:
            return None

        # Fetch recent Nifty prices
        with self.db_manager.session_scope() as session:
            rows = session.query(DailyPriceData).filter(DailyPriceData.symbol == "^NSEI").order_by(DailyPriceData.trade_date.asc()).all()
            
        if not rows:
            return None

        # Build Polars DataFrame and compute 20D EMA using pure Polars
        prices = [{"close": float(row.close)} for row in rows]
        df = pl.DataFrame(prices)
        df = df.with_columns(
            pl.col("close").ewm_mean(span=20, adjust=False).alias("ema_20")
        )
        
        latest_close = df["close"][-1]
        latest_ema = df["ema_20"][-1]

        if latest_close > latest_ema:
            return "SENTIMENT_DIVERGENCE"
            
        return None

    def _save_to_cache(self, result: dict[str, Any]) -> None:
        """Save results to the news_sentiment_cache SQLite table."""
        with self.db_manager.session_scope() as session:
            statement = sqlite_insert(NewsSentimentCache).values(result)
            statement = statement.on_conflict_do_update(
                index_elements=["Date"],
                set_={
                    "Daily_Sentiment_Score": statement.excluded["Daily_Sentiment_Score"],
                    "Raw_Headlines_JSON": statement.excluded["Raw_Headlines_JSON"],
                    "Flags": statement.excluded["Flags"],
                },
            )
            session.execute(statement)

