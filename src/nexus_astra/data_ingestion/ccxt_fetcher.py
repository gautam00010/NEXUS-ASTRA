"""Unified Crypto Fetcher using CCXT."""
import ccxt
import logging
import asyncio

logger = logging.getLogger(__name__)

def fetch_crypto(symbol: str = "BTC/USDT") -> float:
    """
    Fetches live crypto price directly using CCXT unified exchange API.
    Used for cross-asset macro volatility overlays.
    """
    exchange = ccxt.binance({"enableRateLimit": True, "timeout": 10000})
    try:
        ticker = exchange.fetch_ticker(symbol)
        last_price = float(ticker.get("last") or ticker.get("close") or 0.0)
        if last_price > 0:
            return last_price
    except Exception as e:
        logger.warning(f"CCXT Binance fetch failed: {e}. Trying Kraken fallback...")
        try:
            kraken = ccxt.kraken({"enableRateLimit": True, "timeout": 10000})
            ticker = kraken.fetch_ticker(symbol)
            return float(ticker.get("last") or ticker.get("close") or 0.0)
        except Exception as e2:
            logger.error(f"CCXT fallback failed: {e2}")
            raise e

class CCXTFetcher:
    def __init__(self):
        self.exchange = ccxt.binance({
            'enableRateLimit': True,
        })
        
    async def fetch_snapshot(self) -> dict:
        """
        Fetches current BTC/USDT and ETH/USDT tickers using synchronous CCXT
        wrapped in asyncio threads for seamless integration.
        """
        snapshot = {}
        for delay in (2, 4, 8):
            try:
                btc_ticker = await asyncio.to_thread(self.exchange.fetch_ticker, 'BTC/USDT')
                eth_ticker = await asyncio.to_thread(self.exchange.fetch_ticker, 'ETH/USDT')
                
                snapshot['BTC'] = float(btc_ticker['last'])
                snapshot['ETH'] = float(eth_ticker['last'])
                
                if self.exchange.has.get('fetchFundingRate'):
                    funding = await asyncio.to_thread(self.exchange.fetch_funding_rate, 'BTC/USDT')
                    if funding and 'fundingRate' in funding:
                        snapshot['BTC_Funding'] = float(funding['fundingRate'])
                        
                return snapshot
            except Exception as e:
                logger.warning(f"CCXT fetch failed: {e}. Retrying in {delay}s...")
                await asyncio.sleep(delay)
                
        logger.error("CCXT fetch exhausted retries - returning DATA_FAIL")
        return {"status": "DATA_FAIL"}
