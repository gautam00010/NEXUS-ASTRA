"""SEC EDGAR fetcher for ADR filings."""
import logging
import asyncio
import aiohttp
from datetime import datetime, timezone, timedelta
from typing import Any

logger = logging.getLogger(__name__)

# CIK map for Indian ADRs (INFY, WIT)
CIK_MAP = {
    "INFY": "0001067491",
    "WIT": "0001121142",
}

class EdgarFetcher:
    def __init__(self):
        self.headers = {
            "User-Agent": "NexusAstra/3.0 (nexus@example.com)"
        }

    async def fetch_filings(self, symbol: str) -> list[dict[str, Any]]:
        """Fetch 10-K and 8-K filings from SEC EDGAR for ADRs."""
        cik = CIK_MAP.get(symbol)
        if not cik:
            return []
            
        url = f"https://data.sec.gov/submissions/CIK{cik}.json"
        
        try:
            async with aiohttp.ClientSession(headers=self.headers) as session:
                async with session.get(url, timeout=10) as r:
                    if r.status == 200:
                        data = await r.json()
                        recent_filings = data.get("filings", {}).get("recent", {})
                        if not recent_filings:
                            return []
                            
                        forms = recent_filings.get("form", [])
                        dates = recent_filings.get("filingDate", [])
                        
                        results = []
                        for i in range(min(len(forms), 10)):
                            if forms[i] in ["10-K", "8-K", "20-F", "6-K"]: # 20-F/6-K for foreign issuers
                                filing_date = datetime.strptime(dates[i], "%Y-%m-%d").date()
                                pub_dt = datetime.combine(filing_date, datetime.min.time(), tzinfo=timezone.utc)
                                first_allowed = filing_date + timedelta(days=1) # +1 trading day
                                
                                results.append({
                                    "symbol": symbol,
                                    "form": forms[i],
                                    "observation_date": filing_date,
                                    "publication_date": pub_dt,
                                    "first_allowed_date": first_allowed
                                })
                        return results
        except Exception as e:
            logger.warning(f"SEC EDGAR failed for {symbol}: {e}")
            
        return []
