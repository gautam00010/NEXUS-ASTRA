"""VWAP Mean-Reversion Strategy for Indian Liquid Indices (BankNIFTY / NIFTY).

Mechanism:
- Volume Weighted Average Price (VWAP) represents the institutional benchmark price.
- Large algorithmic desks (FII/DII) are evaluated against VWAP:
  * When price extends > VWAP + 2.0 Standard Deviations, algorithmic buying ceases and selling pressure escalates.
  * Price gravitates back toward VWAP.
- Best Assets: BankNIFTY, NIFTY 50, Reliance, HDFC Bank (high institutional participation).
- Avoid on: BSE SME, Microcaps, and illiquid stocks (which can trend runaway without mean-reverting).
- Built using pandas-ta indicator structures.
"""

from __future__ import annotations
import logging
from typing import Any, Dict
import numpy as np
import pandas as pd
import pandas_ta as ta

logger = logging.getLogger(__name__)


def calculate_vwap_bands(
    df: pd.DataFrame,
    std_multiplier: float = 2.0,
) -> pd.DataFrame:
    """
    Computes VWAP and Upper/Lower Standard Deviation Bands using pandas-ta / vector math.
    Expects DataFrame with High, Low, Close, Volume.
    """
    res = df.copy()
    col_map = {c.lower(): c for c in res.columns}
    h_col = col_map.get("high", "High")
    l_col = col_map.get("low", "Low")
    c_col = col_map.get("close", "Close")
    v_col = col_map.get("volume", "Volume")

    typical_price = (res[h_col] + res[l_col] + res[c_col]) / 3.0
    vol = res[v_col].astype(float)

    # Intraday cumulative VWAP
    cum_vol = vol.cumsum()
    cum_vp = (typical_price * vol).cumsum()
    res["VWAP"] = np.where(cum_vol > 0, cum_vp / cum_vol, typical_price)

    # Rolling standard deviation from VWAP
    diff = typical_price - res["VWAP"]
    cum_variance = ((diff ** 2) * vol).cumsum() / np.maximum(cum_vol, 1.0)
    vwap_std = np.sqrt(np.maximum(cum_variance, 0.0))

    res["VWAP_Upper_2s"] = res["VWAP"] + (std_multiplier * vwap_std)
    res["VWAP_Lower_2s"] = res["VWAP"] - (std_multiplier * vwap_std)
    res["VWAP_Std"] = vwap_std

    return res


def generate_vwap_reversion_signal(
    current_price: float = 48500.0,
    vwap: float = 48200.0,
    vwap_std: float = 140.0,
    symbol: str = "BANKNIFTY",
) -> Dict[str, Any]:
    """
    Generates actionable VWAP mean-reversion signal.
    """
    upper_2s = vwap + (2.0 * vwap_std)
    lower_2s = vwap - (2.0 * vwap_std)
    z_score = (current_price - vwap) / max(vwap_std, 1e-5)

    is_liquid_largecap = any(k in symbol.upper() for k in ["NIFTY", "BANKNIFTY", "HDFC", "RELIANCE", "TCS", "ICICI"])

    signal = "NEUTRAL_IN_BAND"
    target = vwap
    stop_loss = current_price

    if not is_liquid_largecap:
        return {
            "strategy": "VWAP Mean-Reversion",
            "symbol": symbol,
            "signal": "BLOCKED_LOW_LIQUIDITY",
            "warning": "VWAP reversion forbidden on low-liquidity/smallcaps. Edge exists only in BankNifty/Nifty large caps.",
            "current_price": current_price,
            "vwap": round(vwap, 2),
            "z_score": round(z_score, 2),
        }

    if current_price >= upper_2s:
        signal = "SHORT_REVERSION"
        target = vwap
        stop_loss = upper_2s + (vwap_std * 0.75)
    elif current_price <= lower_2s:
        signal = "LONG_REVERSION"
        target = vwap
        stop_loss = lower_2s - (vwap_std * 0.75)

    return {
        "strategy": "VWAP Mean-Reversion",
        "symbol": symbol,
        "signal": signal,
        "current_price": round(current_price, 2),
        "vwap": round(vwap, 2),
        "upper_2s": round(upper_2s, 2),
        "lower_2s": round(lower_2s, 2),
        "z_score": round(z_score, 2),
        "target_vwap": round(target, 2),
        "stop_loss": round(stop_loss, 2),
        "institutional_rationale": "Institutions execute around VWAP; extremes > 2 sigma revert as buying exhausts.",
    }
