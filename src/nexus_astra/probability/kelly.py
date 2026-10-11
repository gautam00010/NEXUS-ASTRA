"""Kelly Criterion & Fractional Sizing Engine.

Formula:
  f* = (p * (b + 1) - 1) / b = (p * b - q) / b
  where:
    p = win rate (probability of positive payoff)
    q = 1 - p (probability of loss)
    b = payoff ratio = avg_win / avg_loss

Institutional Edge:
- Full Kelly maximizes the expected logarithmic growth rate of wealth E[log(W_T)].
- However, Full Kelly exhibits extreme volatility and a 33% chance of halving wealth before doubling.
- Institutional desks strictly use Half-Kelly (0.50 * f*) or Quarter-Kelly (0.25 * f*), capped at 12.5%-15.0%.
- Example Benchmark: 55% win rate, 1:1.5 RR -> Full Kelly = 25.0%, Half Kelly = 12.5%.
"""

from __future__ import annotations
import logging
from typing import Any, Dict

logger = logging.getLogger(__name__)


def calculate_institutional_kelly(
    win_rate: float = 0.55,
    payoff_ratio: float = 1.50,
    max_cap_pct: float = 15.0,
    fraction_multiplier: float = 0.50,  # 0.50 for Half-Kelly, 0.25 for Quarter-Kelly
) -> Dict[str, Any]:
    """
    Computes Full Kelly and institutional Fractional (Half/Quarter) Kelly position size.
    Enforces non-negative checks and safety capital caps.
    """
    if win_rate <= 0.0 or win_rate >= 1.0:
        raise ValueError(f"win_rate must be between 0 and 1 exclusive, got {win_rate}")
    if payoff_ratio <= 0.0:
        raise ValueError(f"payoff_ratio must be positive, got {payoff_ratio}")

    p = win_rate
    q = 1.0 - p
    b = payoff_ratio

    # Full Kelly fraction
    full_kelly_fraction = (p * (b + 1.0) - 1.0) / b

    if full_kelly_fraction <= 0.0:
        return {
            "status": "NEGATIVE_EDGE_NO_TRADE",
            "win_rate": round(win_rate, 4),
            "payoff_ratio": round(payoff_ratio, 2),
            "full_kelly_pct": 0.0,
            "fractional_kelly_pct": 0.0,
            "recommended_allocation_pct": 0.0,
            "guidance": f"Negative edge (Full Kelly: {full_kelly_fraction * 100:.2f}%). Trading guaranteed to lose money.",
        }

    fractional_fraction = full_kelly_fraction * fraction_multiplier
    fractional_pct = round(fractional_fraction * 100.0, 2)
    full_kelly_pct = round(full_kelly_fraction * 100.0, 2)

    # Apply strict risk cap
    recommended_pct = min(fractional_pct, max_cap_pct)

    # Theoretical risk of 50% drawdown under Full vs Half Kelly
    # Under Full Kelly: P(50% DD) = 50%; Under Half Kelly: P(50% DD) ~ 11%
    p_half_wealth_drawdown = 0.50 if fraction_multiplier >= 1.0 else 0.11

    return {
        "status": "APPROVED",
        "win_rate": round(win_rate, 4),
        "payoff_ratio": round(payoff_ratio, 2),
        "full_kelly_pct": full_kelly_pct,
        "half_kelly_pct": round(full_kelly_fraction * 0.50 * 100.0, 2),
        "fractional_kelly_pct": fractional_pct,
        "fraction_multiplier": fraction_multiplier,
        "max_cap_pct": max_cap_pct,
        "recommended_allocation_pct": recommended_pct,
        "prob_50pct_drawdown": p_half_wealth_drawdown,
        "guidance": (
            f"Full Kelly {full_kelly_pct:.1f}% scaled down by {fraction_multiplier:.2f}x to Half-Kelly "
            f"({fractional_pct:.1f}%). Capped at {recommended_pct:.1f}% max capital. Protects against tail volatility."
        ),
    }
