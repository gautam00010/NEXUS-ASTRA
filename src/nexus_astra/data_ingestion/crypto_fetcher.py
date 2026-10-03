"""Crypto fetcher for Binance and CoinGecko (free tiers) via CCXT."""
import logging
import asyncio
import aiohttp
from typing import Any
import ccxt.async_support as ccxt_async

logger = logging.getLogger(__name__)

class CryptoFetcher:
    def __init__(self):
        pass

    async def fetch_prices(self) -> dict[str, Any]:
        """Fetch BTC and ETH prices using CCXT and CoinGecko."""
        prices = {}
        
        # 1. CCXT Binance Primary
        try:
            exchange = ccxt_async.binance()
            ticker_btc = await exchange.fetch_ticker('BTC/USDT')
            prices["BTC"] = ticker_btc['last']
            
            ticker_eth = await exchange.fetch_ticker('ETH/USDT')
            prices["ETH"] = ticker_eth['last']
            
            try:
                # Funding rate
                funding = await exchange.fetch_funding_rate('BTC/USDT:USDT')
                if funding and 'fundingRate' in funding:
                    prices["BTC_Funding"] = float(funding['fundingRate'])
            except Exception as e2:
                logger.warning(f"CCXT Binance funding rate failed: {e2}")
                
            await exchange.close()
        except Exception as e:
            logger.warning(f"CCXT Binance API failed: {e}")

        # 2. CoinGecko Backup
        try:
            url = "https://api.coingecko.com/api/v3/simple/price?ids=bitcoin,ethereum&vs_currencies=inr,usd&include_24hr_vol=true"
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=5) as r:
                    if r.status == 200:
                        data = await r.json()
                        if "bitcoin" in data and "BTC" not in prices:
                            prices["BTC"] = data["bitcoin"]["usd"]
                        if "ethereum" in data and "ETH" not in prices:
                            prices["ETH"] = data["ethereum"]["usd"]
        except Exception as e:
            logger.warning(f"CoinGecko API failed: {e}")
            
        return prices
