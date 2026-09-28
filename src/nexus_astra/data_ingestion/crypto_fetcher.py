"""Crypto fetcher for Binance and CoinGecko (free tiers)."""
import logging
import asyncio
import aiohttp
from typing import Any

logger = logging.getLogger(__name__)

class CryptoFetcher:
    def __init__(self):
        pass

    async def fetch_prices(self) -> dict[str, Any]:
        """Fetch BTC and ETH prices from Binance and CoinGecko."""
        prices = {}
        
        # 1. Binance Primary
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get("https://api.binance.com/api/v3/ticker/price?symbol=BTCUSDT", timeout=5) as r:
                    if r.status == 200:
                        data = await r.json()
                        prices["BTC"] = float(data["price"])
                
                async with session.get("https://fapi.binance.com/fapi/v1/fundingRate?symbol=BTCUSDT&limit=1", timeout=5) as r:
                    if r.status == 200:
                        data = await r.json()
                        if data:
                            prices["BTC_Funding"] = float(data[0]["fundingRate"])
        except Exception as e:
            logger.warning(f"Binance API failed: {e}")

        # 2. CoinGecko Backup
        try:
            url = "https://api.coingecko.com/api/v3/simple/price?ids=bitcoin,ethereum&vs_currencies=inr,usd&include_24hr_vol=true"
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=5) as r:
                    if r.status == 200:
                        data = await r.json()
                        if "bitcoin" in data and "BTC" not in prices:
                            prices["BTC"] = data["bitcoin"]["usd"]
                        if "ethereum" in data:
                            prices["ETH"] = data["ethereum"]["usd"]
        except Exception as e:
            logger.warning(f"CoinGecko API failed: {e}")
            
        return prices
