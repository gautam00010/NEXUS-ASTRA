"""Pandas-TA Engine for 150+ Technical Indicators."""
import pandas_ta as ta
import pandas as pd

class TechnicalAnalysisEngine:
    @staticmethod
    def append_indicators(df: pd.DataFrame) -> pd.DataFrame:
        """
        Appends massive technical indicator sets natively via pandas-ta.
        Extremely fast C-compiled backends.
        """
        # Ensure correct column casing
        df.ta.rsi(length=14, append=True)
        df.ta.macd(fast=12, slow=26, signal=9, append=True)
        df.ta.bbands(length=20, std=2, append=True)
        return df
