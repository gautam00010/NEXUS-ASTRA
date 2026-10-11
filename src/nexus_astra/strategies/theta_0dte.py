"""Options 0DTE Theta Decay Expiry Strategy for NIFTY / BankNIFTY (OpenAlgo Router).

Microstructure Mathematics:
- In option pricing (Black-Scholes-Merton), Theta decay is non-linear:
    Theta ∝ 1 / (2 * sqrt(T))
- In the final 60 minutes of weekly expiry (e.g. Thursday 2:30 PM - 3:30 PM IST),
  time value (extrinsic premium) evaporates at its fastest historical velocity.
- Strategy Rules:
  * Trigger: Thursday (or monthly expiry day) precisely at 2:30 PM IST.
  * Selection: Sell far Out-of-the-Money (OTM) Strangle (1.5% OTM Call + 1.5% OTM Put).
  * Holding Duration: 45 minutes max -> Mandatory covering by 3:15 PM IST.
  * Critical Stop-Loss: Hard stop at 100% premium loss (if option jumps from ₹15 to ₹30, instantly cut).
  * Gamma Risk Warning: Extreme risk; gamma can double the option price in seconds during late-day squeezes.
- Executable via OpenAlgo Indian Broker API.
"""

from __future__ import annotations
import logging
from typing import Any, Dict
import numpy as np

logger = logging.getLogger(__name__)


def generate_0dte_strangle_strikes(
    spot_price: float = 22100.0,
    otm_pct: float = 0.015,  # 1.5% OTM
    strike_step: int = 50,    # NIFTY 50-point strike steps
) -> Dict[str, Any]:
    """
    Computes far OTM 0DTE strangle strikes and risk thresholds for Thursday expiry.
    """
    raw_ce = spot_price * (1.0 + otm_pct)
    raw_pe = spot_price * (1.0 - otm_pct)

    ce_strike = int(round(raw_ce / strike_step) * strike_step)
    pe_strike = int(round(raw_pe / strike_step) * strike_step)

    # Synthetic baseline pricing for 1.5% OTM options at 2:30 PM on expiry day
    est_ce_prem = round(max(3.5, (spot_price * 0.0006)), 1)
    est_pe_prem = round(max(3.5, (spot_price * 0.0006)), 1)
    total_prem = est_ce_prem + est_pe_prem

    return {
        "strategy": "Options 0DTE Weekly Expiry Theta Burn",
        "underlying": "NIFTY 50",
        "spot_price": round(spot_price, 2),
        "otm_distance_pct": round(otm_pct * 100.0, 2),
        "ce_strike": ce_strike,
        "ce_estimated_premium": est_ce_prem,
        "pe_strike": pe_strike,
        "pe_estimated_premium": est_pe_prem,
        "total_premium_collected": total_prem,
        "entry_time": "14:30 IST (Thursday)",
        "exit_time": "15:15 IST (Hard auto-square-off)",
        "stop_loss_ce_prem": round(est_ce_prem * 2.0, 1),  # 100% stop
        "stop_loss_pe_prem": round(est_pe_prem * 2.0, 1),
        "openalgo_order_template": {
            "broker": "OPENALGO_NSE",
            "strategy": "THETA_0DTE_STRANGLE",
            "legs": [
                {"action": "SELL", "symbol": f"NIFTY{ce_strike}CE", "quantity": 50, "order_type": "MARKET"},
                {"action": "SELL", "symbol": f"NIFTY{pe_strike}PE", "quantity": 50, "order_type": "MARKET"},
            ],
            "max_loss_rs": total_prem * 50,
        },
        "gamma_warning": "High gamma risk: sudden 50-pt index move can 3x the premium. Strict stops non-negotiable.",
    }


def simulate_0dte_decay(
    starting_premium: float = 24.0,
    minutes_remaining: int = 45,
) -> Dict[str, Any]:
    """
    Simulates non-linear theta burn in the final 45 minutes of trading.
    """
    # Square-root time decay
    t = np.linspace(1, 0.05, minutes_remaining)
    decay_curve = starting_premium * np.sqrt(t)

    return {
        "starting_premium": starting_premium,
        "final_projected_premium": round(float(decay_curve[-1]), 2),
        "captured_theta_pct": round(float((1.0 - decay_curve[-1] / starting_premium) * 100.0), 1),
        "edge": "Accelerated non-linear extrinsic value decay into 3:30 PM settlement.",
    }
