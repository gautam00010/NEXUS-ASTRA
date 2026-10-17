"""Pandas-TA Engine for 150+ Technical Indicators with fallback."""
try:
    import pandas_ta as ta
except (ImportError, Exception):
    try:
        import pandas_ta_classic as ta
    except (ImportError, Exception):
        ta = None

import pandas as pd
import numpy as np


class TechnicalAnalysisEngine:
    @staticmethod
    def append_indicators(df: pd.DataFrame) -> pd.DataFrame:
        """
        Appends technical indicator sets natively via pandas-ta if present,
        or uses vectorised pandas/numpy fallback.
        """
        if ta is not None and hasattr(df, "ta"):
            try:
                df.ta.rsi(length=14, append=True)
                df.ta.macd(fast=12, slow=26, signal=9, append=True)
                df.ta.bbands(length=20, std=2, append=True)
                return df
            except Exception:
                pass

        # Vectorised fallback for RSI, MACD, BBands
        c_col = "close" if "close" in df.columns else ("Close" if "Close" in df.columns else df.columns[0])
        close = df[c_col]
        # RSI 14
        delta = close.diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        rs = gain / loss.replace(0, np.nan)
        df["RSI_14"] = (100 - (100 / (1 + rs))).fillna(50.0)

        # MACD (12, 26, 9)
        ema12 = close.ewm(span=12, adjust=False).mean()
        ema26 = close.ewm(span=26, adjust=False).mean()
        df["MACD_12_26_9"] = ema12 - ema26
        df["MACDs_12_26_9"] = df["MACD_12_26_9"].ewm(span=9, adjust=False).mean()
        df["MACDh_12_26_9"] = df["MACD_12_26_9"] - df["MACDs_12_26_9"]

        # BBands (20, 2)
        mid = close.rolling(20).mean()
        std = close.rolling(20).std()
        df["BBM_20_2.0"] = mid
        df["BBU_20_2.0"] = mid + 2 * std
        df["BBL_20_2.0"] = mid - 2 * std
        return df

