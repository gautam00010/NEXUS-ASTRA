"""QuantStats Analytics Engine for automated tear sheets."""
import quantstats as qs
import pandas as pd
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

class QuantStatsEngine:
    @staticmethod
    def generate_tear_sheet(returns: pd.Series, output_path: str = "logs/quantstats_tearsheet.html"):
        """
        Generates a comprehensive QuantStats tear sheet (HTML report).
        Includes Sharpe (after costs), DD, and performance metrics.
        """
        try:
            # Ensure index is datetime for quantstats
            if not isinstance(returns.index, pd.DatetimeIndex):
                returns.index = pd.to_datetime(returns.index)
                
            qs.reports.html(returns, output=output_path, title="NEXUS-ASTRA Live Tear Sheet")
            logger.info(f"QuantStats tear sheet generated at {output_path}")
        except Exception as e:
            logger.warning(f"QuantStats generation failed: {e}")
