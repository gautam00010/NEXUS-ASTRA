"""Unified Crypto Fetcher using CCXT."""
import ccxt
import logging
import asyncio
from sqlalchemy import desc

from nexus_astra.data_ingestion.database import PricesRaw, database_manager

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
            fallback_price = _load_latest_cached_crypto_price(symbol)
            if fallback_price is not None and fallback_price > 0:
                logger.warning(
                    f"Using cached crypto price for {symbol} from prices_raw due network failure: {fallback_price}"
                )
                return fallback_price
            raise e


def _load_latest_cached_crypto_price(symbol: str) -> float | None:
    symbol_upper = symbol.upper()
    candidates = {
        "BTC/USDT": ["BTC-USD", "BTCUSDT", "BTC", "XBTUSD"],
        "ETH/USDT": ["ETH-USD", "ETHUSDT", "ETH"],
    }.get(symbol_upper, [symbol_upper.replace("/", "-"), symbol_upper.replace("/", "")])

    try:
        with database_manager.session_scope() as session:
            row = (
                session.query(PricesRaw)
                .filter(PricesRaw.symbol.in_(candidates))
                .order_by(desc(PricesRaw.trade_date))
                .first()
            )
            if row and row.close is not None:
                return float(row.close)
    except Exception as exc:
        logger.debug(f"Cached crypto fallback lookup failed: {exc}")
    return None

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
