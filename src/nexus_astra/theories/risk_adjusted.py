"""Risk-Adjusted Return Metrics: Sharpe vs Sortino for Indian Markets.

Core Principle:
- Never sort trades or portfolios by nominal return alone.
- Example:
  Strategy A: 30% Return with 40% Volatility -> Sharpe = 0.75 (high gambler variance, dangerous drawdowns).
  Strategy B: 15% Return with 10% Volatility -> Sharpe = 1.50 (institutional skill, stable compounding).
- In Indian Equities (high retail beta, gap risk, fat left tails):
  Sortino ratio is superior to Sharpe because it only penalizes downside volatility:
  Downside Vol = sqrt( mean( min(0, R_t - MAR)^2 ) )
  Upside volatility is rewarded, while gap downs and tail events are rigorously penalized.
"""

from __future__ import annotations
import logging
from typing import Any, Dict, List
import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


def calculate_sharpe_ratio(
    returns: pd.Series | np.ndarray,
    rf_annual: float = 0.065,  # 6.5% Indian 10-Year G-Sec risk-free rate
    periods_per_year: int = 252,
) -> float:
    """
    Calculate annualized Sharpe ratio:
      Sharpe = (E[R] - Rf) / Volatility
    """
    arr = np.asarray(returns, dtype=float)
    if len(arr) < 2:
        return 0.0
    rf_period = rf_annual / periods_per_year
    excess = arr - rf_period
    std = np.std(arr, ddof=1)
    if std <= 1e-9:
        return 0.0
    return float((np.mean(excess) / std) * np.sqrt(periods_per_year))


def calculate_sortino_ratio(
    returns: pd.Series | np.ndarray,
    rf_annual: float = 0.065,  # 6.5% G-Sec risk-free rate
    mar_annual: float = 0.065, # Minimum Acceptable Return
    periods_per_year: int = 252,
) -> float:
    """
    Calculate annualized Sortino ratio:
      Sortino = (E[R] - Rf) / Downside_Deviation
    """
    arr = np.asarray(returns, dtype=float)
    if len(arr) < 2:
        return 0.0
    rf_period = rf_annual / periods_per_year
    mar_period = mar_annual / periods_per_year

    excess = arr - rf_period
    downside_diff = np.minimum(0.0, arr - mar_period)
    downside_dev = np.sqrt(np.mean(downside_diff ** 2))

    if downside_dev <= 1e-9:
        return 0.0
    return float((np.mean(excess) / downside_dev) * np.sqrt(periods_per_year))


def rank_strategies_risk_adjusted(strategies: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Ranks strategies by Risk-Adjusted metrics (Sharpe & Sortino) rather than raw return.
    Demonstrates why 30% return / 40% vol is inferior to 15% return / 10% vol.
    """
    results = []
    for s in strategies:
        ret = s.get("annual_return_pct", 15.0)
        vol = s.get("annual_vol_pct", 15.0)
        downside_vol = s.get("annual_downside_vol_pct", vol * 0.70)
        rf = s.get("rf_pct", 6.5)

        sharpe = (ret - rf) / max(vol, 1.0)
        sortino = (ret - rf) / max(downside_vol, 1.0)

        results.append({
            "name": s.get("name", "Strategy"),
            "annual_return_pct": ret,
            "annual_vol_pct": vol,
            "annual_downside_vol_pct": downside_vol,
            "sharpe_ratio": round(sharpe, 2),
            "sortino_ratio": round(sortino, 2),
            "verdict": (
                "INSTITUTIONAL_SKILL" if sharpe >= 1.5
                else ("MARKET_BETA_LUCK" if sharpe >= 0.8 else "HIGH_RISK_GAMBLING")
            ),
        })

    # Sort descending by Sharpe Ratio
    results.sort(key=lambda x: x["sharpe_ratio"], reverse=True)
    return results


def get_canonical_indian_comparison() -> Dict[str, Any]:
    """Canonical demonstration of why Indian quants prioritize Sortino over absolute return."""
    comparison = [
        {
            "name": "High-Beta Smallcap Chaser",
            "annual_return_pct": 30.0,
            "annual_vol_pct": 40.0,
            "annual_downside_vol_pct": 32.0,
            "rf_pct": 6.5,
        },
        {
            "name": "Nifty Systematic Trend / Quality",
            "annual_return_pct": 18.0,
            "annual_vol_pct": 11.0,
            "annual_downside_vol_pct": 6.5,
            "rf_pct": 6.5,
        },
        {
            "name": "Low-Vol Momentum Swing (BSE/NSE)",
            "annual_return_pct": 15.0,
            "annual_vol_pct": 10.0,
            "annual_downside_vol_pct": 5.2,
            "rf_pct": 6.5,
        },
    ]
    ranked = rank_strategies_risk_adjusted(comparison)
    return {
        "ranked_strategies": ranked,
        "key_insight": (
            "Strategy with 30% return has lowest Sharpe (0.59) and catastrophic drawdown risk. "
            "Systematic 15% with 10% vol achieves Sharpe 0.85 and Sortino 1.63, compounding sustainably."
        ),
    }
