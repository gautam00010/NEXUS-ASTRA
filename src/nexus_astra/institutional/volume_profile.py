"""Model 4: Intraday Volume Profile & Order Flow Cumulative Delta Model.

Mechanism:
- Auction Market Theory (Steidlmayer / Market Profile):
  * Value Area High (VAH): The upper boundary containing 70% of traded volume.
  * Point of Control (POC): The single price node where maximum volume was transacted.
  * Value Area Low (VAL): The lower boundary containing 70% of traded volume.
- Institutional Order Flow Imbalance (Cumulative Delta):
  * Delta = Aggressive Buyer Volume (Ask) - Aggressive Seller Volume (Bid).
  * Institutional Accumulation Setup:
    1. Current price accepts and holds above previous day's Value Area High (VAH).
    2. Cumulative order flow delta exceeds +2,000,000 shares (+2M shares).
  * Holding Period: 2 to 4 hours (LFT intraday), aligning with institutional VWAP TWAP algorithms.
"""

from __future__ import annotations
import logging
from typing import Any, Dict
import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


def compute_volume_profile_nodes(
    prices: np.ndarray | pd.Series,
    volumes: np.ndarray | pd.Series,
    num_bins: int = 30,
    value_area_pct: float = 0.70,
) -> Dict[str, float]:
    """
    Computes Point of Control (POC), Value Area High (VAH), and Value Area Low (VAL).
    """
    p = np.asarray(prices, dtype=float)
    v = np.asarray(volumes, dtype=float)

    if len(p) < 10 or np.sum(v) <= 0:
        base_p = float(p[-1]) if len(p) > 0 else 22100.0
        return {"poc": base_p, "vah": base_p * 1.004, "val": base_p * 0.996}

    bins = np.linspace(np.min(p), np.max(p), num_bins)
    bin_indices = np.digitize(p, bins) - 1
    bin_indices = np.clip(bin_indices, 0, num_bins - 1)

    vol_profile = np.zeros(num_bins)
    for idx, vol in zip(bin_indices, v):
        vol_profile[idx] += vol

    poc_idx = int(np.argmax(vol_profile))
    poc_price = float(bins[poc_idx])

    # Compute Value Area (70% of total volume expanding outward from POC)
    total_vol = np.sum(vol_profile)
    target_vol = total_vol * value_area_pct

    current_vol = vol_profile[poc_idx]
    low_idx = poc_idx
    high_idx = poc_idx

    while current_vol < target_vol and (low_idx > 0 or high_idx < num_bins - 1):
        left_vol = vol_profile[low_idx - 1] if low_idx > 0 else 0
        right_vol = vol_profile[high_idx + 1] if high_idx < num_bins - 1 else 0

        if left_vol >= right_vol and low_idx > 0:
            low_idx -= 1
            current_vol += left_vol
        elif high_idx < num_bins - 1:
            high_idx += 1
            current_vol += right_vol
        else:
            break

    val_price = float(bins[low_idx])
    vah_price = float(bins[high_idx])

    return {
        "poc": round(poc_price, 2),
        "vah": round(vah_price, 2),
        "val": round(val_price, 2),
    }


def evaluate_volume_profile_imbalance(
    current_price: float = 22180.0,
    prev_vah: float = 22120.0,
    prev_val: float = 22020.0,
    prev_poc: float = 22070.0,
    cumulative_delta_shares: float = 2_450_000.0,  # +2.45M shares delta
    current_volume: float = 12_500_000.0,
) -> Dict[str, Any]:
    """
    Evaluates price acceptance relative to Value Area and Cumulative Order Flow Delta.
    """
    accepted_above_vah = current_price > prev_vah
    accepted_below_val = current_price < prev_val
    strong_buy_delta = cumulative_delta_shares >= 2_000_000.0
    strong_sell_delta = cumulative_delta_shares <= -2_000_000.0

    if accepted_above_vah and strong_buy_delta:
        signal = "LONG_ACCEPTANCE_ABOVE_VAH"
        action = "BUY_LONG_VALUE_ACCEPTANCE"
        target = current_price + (prev_vah - prev_poc) * 1.5
        stop_loss = prev_vah * 0.998  # Back below VAH invalidates
        guidance = (
            f"Price (₹{current_price}) accepted above previous day VAH (₹{prev_vah}) with "
            f"cumulative delta +{cumulative_delta_shares/1e6:.2f}M shares. Hold 2-4 hours; target ₹{target:.1f}."
        )
    elif accepted_below_val and strong_sell_delta:
        signal = "BEARISH_VALUE_EXPANSION_SHORT"
        action = "SELL_SHORT_VALUE_REJECTION"
        target = current_price - (prev_poc - prev_val) * 1.5
        stop_loss = prev_val * 1.002
        guidance = (
            f"Price (₹{current_price}) rejected below previous day VAL (₹{prev_val}) with "
            f"negative delta {cumulative_delta_shares/1e6:.2f}M shares. Target ₹{target:.1f}."
        )
    else:
        signal = "VALUE_ROTATION_BALANCED"
        action = "TRADE_POC_REVERSION"
        target = prev_poc
        stop_loss = prev_val if current_price > prev_poc else prev_vah
        guidance = f"Price trading within previous value area (₹{prev_val} - ₹{prev_vah}). Expect rotation toward POC (₹{prev_poc})."

    return {
        "model": "Model 4: Intraday Volume Profile + Order Flow Delta",
        "current_price": round(current_price, 2),
        "prev_vah": round(prev_vah, 2),
        "prev_val": round(prev_val, 2),
        "prev_poc": round(prev_poc, 2),
        "cumulative_delta_shares": round(cumulative_delta_shares, 1),
        "signal": signal,
        "action": action,
        "target": round(target, 2),
        "stop_loss": round(stop_loss, 2),
        "holding_horizon": "2 - 4 Hours LFT Intraday",
        "guidance": guidance,
    }
