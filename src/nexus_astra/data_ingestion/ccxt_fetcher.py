"""Unified Crypto Fetcher using CCXT."""
import ccxt
import logging
import asyncio

logger = logging.getLogger(__name__)

class CCXTFetcher:
    def __init__(self):
        # Initialize unified exchange
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
                # CCXT unified API
                btc_ticker = await asyncio.to_thread(self.exchange.fetch_ticker, 'BTC/USDT')
                eth_ticker = await asyncio.to_thread(self.exchange.fetch_ticker, 'ETH/USDT')
                
                snapshot['BTC'] = float(btc_ticker['last'])
                snapshot['ETH'] = float(eth_ticker['last'])
                
                # Fetch funding rate if available
                if self.exchange.has['fetchFundingRate']:
                    funding = await asyncio.to_thread(self.exchange.fetch_funding_rate, 'BTC/USDT')
                    if funding and 'fundingRate' in funding:
                        snapshot['BTC_Funding'] = float(funding['fundingRate'])
                        
                return snapshot
            except Exception as e:
                logger.warning(f"CCXT fetch failed: {e}. Retrying in {delay}s...")
                await asyncio.sleep(delay)
                
        logger.error("CCXT fetch exhausted retries - returning DATA_FAIL")
        return {"status": "DATA_FAIL"}
