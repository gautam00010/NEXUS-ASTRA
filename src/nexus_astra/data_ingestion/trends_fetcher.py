"""Google Trends fetcher."""
import logging
import asyncio
import time
from typing import Any
import pandas as pd
import numpy as np

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
