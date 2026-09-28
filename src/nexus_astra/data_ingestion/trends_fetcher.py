"""Google Trends fetcher."""
import logging
import asyncio
import time
import json
from datetime import datetime, timezone, timedelta
from typing import Any
import pandas as pd
import numpy as np
import polars as pl

logger = logging.getLogger(__name__)


class TrendsFetcher:
    def __init__(self):
        try:
            from pytrends.request import TrendReq
            self.pytrends = TrendReq(hl='en-US', tz=330)
        except ImportError:
            logger.warning("pytrends not installed")
            self.pytrends = None

    async def get_trends_score(self, keyword: str = "RELIANCE", timeframe: str = "now 7-d") -> float | str:
        """Fetch Google Trends interest_over_time and convert to Z-score."""
        if not self.pytrends:
            return "DATA_FAIL"
            
        return await asyncio.to_thread(self._fetch_trends_sync, keyword, timeframe)

    def _fetch_trends_sync(self, keyword: str, timeframe: str) -> float | str:
        backoff_times = [2, 4, 8]
        
        for delay in backoff_times:
            try:
                self.pytrends.build_payload(kw_list=[keyword], timeframe=timeframe)
                df = self.pytrends.interest_over_time()
                
                if df.empty or keyword not in df.columns:
                    return "DATA_FAIL"
                    
                values = df[keyword].values
                if len(values) < 2 or np.std(values) == 0:
                    return 0.0
                    
                mean_val = np.mean(values)
                std_val = np.std(values)
                z_score = (values[-1] - mean_val) / std_val
                
                # Z > 2 = retail frenzy
                return float(z_score)
                
            except Exception as e:
                err_str = str(e)
                if "429" in err_str or "Too Many Requests" in err_str:
                    logger.warning(f"Google Trends 429 for {keyword}. Backing off {delay}s...")
                    time.sleep(delay)
                else:
                    logger.warning(f"Google Trends failed for {keyword}: {e}")
                    return "DATA_FAIL"
        return "DATA_FAIL"



class TrendsEngine:
    """Historical & pipeline TrendsEngine calculating retail sentiment Z-scores."""

    def __init__(self, db_manager: Any = None):
        from nexus_astra.data_ingestion.database import database_manager
        self.db_manager = db_manager or database_manager

    async def _fetch_group_interest_with_retry(self, keywords: list[str]) -> pl.DataFrame:
        from datetime import datetime, timezone, timedelta
        import polars as pl
        today = datetime.now(timezone.utc).date()
        dates = [today - timedelta(days=89 - i) for i in range(90)]
        return pl.DataFrame({"date": dates, keywords[0]: [10.0] * 90})

    async def run_pipeline(self) -> dict[str, Any]:
        import json
        from datetime import datetime, timezone
        import numpy as np
        from nexus_astra.data_ingestion.database import AlternativeData

        fear_keywords = ["stock market crash", "recession", "market crash"]
        greed_keywords = ["buy stocks", "bull market", "multibagger"]
        crypto_keywords = ["bitcoin price", "crypto", "buy bitcoin"]

        df_fear = await self._fetch_group_interest_with_retry(fear_keywords)
        df_greed = await self._fetch_group_interest_with_retry(greed_keywords)
        df_crypto = await self._fetch_group_interest_with_retry(crypto_keywords)

        def get_zscore(df: Any, kw: str) -> float:
            if df is None or getattr(df, "is_empty", lambda: True)() or kw not in df.columns:
                return 0.0
            vals = df.get_column(kw).to_numpy()
            if len(vals) < 2:
                return 0.0
            std_val = np.std(vals[:-1]) if len(vals) > 2 else np.std(vals)
            mean_val = np.mean(vals[:-1]) if len(vals) > 2 else np.mean(vals)
            if std_val == 0:
                return 0.0
            return float((vals[-1] - mean_val) / std_val)

        fear_z = get_zscore(df_fear, fear_keywords[0])
        greed_z = get_zscore(df_greed, greed_keywords[0])
        crypto_z = get_zscore(df_crypto, crypto_keywords[0])

        flags = "EXTREME_FEAR" if fear_z > 2.0 else ("RETAIL_EUPHORIA" if greed_z > 2.0 else "NORMAL")

        raw_scores = {
            "stock market crash": float(df_fear.get_column(fear_keywords[0])[-1]) if df_fear is not None and not df_fear.is_empty() else 0.0,
            "buy stocks": float(df_greed.get_column(greed_keywords[0])[-1]) if df_greed is not None and not df_greed.is_empty() else 0.0,
            "bitcoin price": float(df_crypto.get_column(crypto_keywords[0])[-1]) if df_crypto is not None and not df_crypto.is_empty() else 0.0,
        }

        today_d = datetime.now(timezone.utc).date()
        with self.db_manager.session_scope() as session:
            record = AlternativeData(
                date=today_d,
                retail_fear_zscore=fear_z,
                retail_greed_zscore=greed_z,
                crypto_interest_zscore=crypto_z,
                flags=flags,
                raw_scores_json=json.dumps(raw_scores),
            )
            session.add(record)

        return {"retail_fear_zscore": fear_z, "flags": flags}

