import logging
from datetime import date
import polars as pl

from nexus_astra.data_ingestion.database import database_manager, DailyPriceData, PricesRaw, SectorMetrics

logger = logging.getLogger(__name__)

# Core NSE Sector Indices
SECTORS = [
    "NIFTY BANK",
    "NIFTY IT",
    "NIFTY AUTO",
    "NIFTY PHARMA",
    "NIFTY METAL",
    "NIFTY FMCG"
]

SECTOR_SYMBOL_MAP = {
    "NIFTY 50": "^NSEI",
    "NIFTY BANK": "^NSEBANK",
    "NIFTY IT": "NIFTY_IT",
    "NIFTY AUTO": "NIFTY_AUTO",
    "NIFTY PHARMA": "NIFTY_PHARMA",
    "NIFTY METAL": "NIFTY_METAL",
    "NIFTY FMCG": "NIFTY_FMCG"
}

class SectorRotation:
    """Calculates sector relative strength and rotation signals using real price history."""

    def __init__(self):
        self.lookback_days = 20

    def fetch_historical_data(self, symbol: str, days: int) -> pl.DataFrame:
        """Fetches real historical close prices from database or returns empty frame."""
        db_symbol = SECTOR_SYMBOL_MAP.get(symbol, symbol)
        try:
            with database_manager.session_scope() as session:
                rows = (
                    session.query(DailyPriceData.trade_date, DailyPriceData.close)
                    .filter((DailyPriceData.symbol == db_symbol) | (DailyPriceData.symbol == symbol))
                    .order_by(DailyPriceData.trade_date.desc())
                    .limit(days + 5)
                    .all()
                )
                if not rows or len(rows) < 2:
                    return pl.DataFrame(schema={"Date": pl.Date, "Close": pl.Float64})

                rows.reverse()
                return pl.DataFrame({
                    "Date": [r[0] for r in rows],
                    "Close": [float(r[1]) for r in rows],
                })
        except Exception as e:
            logger.error(f"Failed to fetch data for {symbol}: {e}")
            return pl.DataFrame(schema={"Date": pl.Date, "Close": pl.Float64})

    def analyze_sectors(self) -> dict[str, dict]:
        """Calculates RS for all tracked sectors against Nifty 50 using pure Polars (close / close.shift(20) - 1)."""
        nifty_df = self.fetch_historical_data("NIFTY 50", self.lookback_days)
        if len(nifty_df) >= 2:
            nifty_df = nifty_df.with_columns(
                ((pl.col("Close") / pl.col("Close").shift(self.lookback_days) - 1.0)).alias("Return_20d")
            )
            nifty_return = float(nifty_df["Return_20d"][-1]) if nifty_df["Return_20d"][-1] is not None else 0.0
            if nifty_return == 0.0:
                nifty_return = float((nifty_df["Close"][-1] - nifty_df["Close"][0]) / nifty_df["Close"][0])
        else:
            nifty_return = 0.0

        results = {}
        with database_manager.session_scope() as session:
            for sector in SECTORS:
                sector_df = self.fetch_historical_data(sector, self.lookback_days)
                if len(sector_df) >= 2:
                    sector_df = sector_df.with_columns(
                        ((pl.col("Close") / pl.col("Close").shift(self.lookback_days) - 1.0)).alias("Return_20d")
                    )
                    sector_return = float(sector_df["Return_20d"][-1]) if sector_df["Return_20d"][-1] is not None else 0.0
                    if sector_return == 0.0:
                        sector_return = float((sector_df["Close"][-1] - sector_df["Close"][0]) / sector_df["Close"][0])
                else:
                    # Missing data returns 0.0, never random numbers
                    sector_return = 0.0

                # Relative Strength against NIFTY 50
                rs = (1.0 + sector_return) / (1.0 + nifty_return) if (1.0 + nifty_return) != 0 else 1.0

                classification = "NEUTRAL"
                flags = None

                if rs > 1.10:
                    classification = "LEADER"
                    flags = "STRONG_TREND"
                elif rs < 0.90:
                    classification = "LAGGARD"
                    flags = "CAPITULATION_SETUP"

                if rs > 1.05 and sector_return > 0.03 and nifty_return < 0.01:
                    flags = "SECTOR_ROTATION_IN_PROGRESS"

                existing = session.query(SectorMetrics).filter_by(
                    sector=sector,
                    date=date.today()
                ).first()

                if not existing:
                    metrics = SectorMetrics(
                        sector=sector,
                        date=date.today(),
                        relative_strength_20d=float(rs),
                        classification=classification,
                        flags=flags
                    )
                    session.add(metrics)

                results[sector] = {
                    "rs": float(rs),
                    "classification": classification,
                    "flags": flags
                }

        logger.info(f"Sector Rotation analysis complete for {len(results)} sectors.")
        return results
