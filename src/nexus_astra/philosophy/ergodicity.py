"""Ergodicity Economics & Path-Dependent Survival Engine (Ole Peters / Taleb).

Principle:
- In non-ergodic systems like financial markets:
    Ensemble Average != Time Average
- An investment strategy with positive ensemble expectation (+10% across 1,000 parallel universes)
  can lead to 100% ruin for an individual navigating a single path over time.
- The Asymmetry of Drawdowns:
  * -10% loss requires +11.1% gain to recover.
  * -20% loss requires +25.0% gain to recover.
  * -50% loss requires +100.0% gain to recover.
  * -80% loss requires +400.0% gain to recover.
  * -90% loss requires +900.0% gain to recover.
- Core Institutional Rule:
  Drawdown avoidance dominates return maximization. Survival is the non-negotiable prerequisite to compounding.
"""

from __future__ import annotations
import logging
from typing import Any, Dict

logger = logging.getLogger(__name__)


def compute_ergodicity_recovery_burden(current_drawdown_pct: float) -> Dict[str, Any]:
    """
    Computes required return to recover to high-water mark and assesses absorbing barrier risk.
    """
    dd = abs(current_drawdown_pct)
    if dd >= 100.0:
        return {
            "current_drawdown_pct": 100.0,
            "required_recovery_gain_pct": float("inf"),
            "absorbing_barrier_hit": True,
            "survival_status": "TERMINAL_RUIN",
            "advisory": "Total capital depletion. The timeline has terminated.",
        }

    # Recovery formula: R_needed = (1 / (1 - dd/100)) - 1
    recovery_gain_pct = round(((1.0 / (1.0 - (dd / 100.0))) - 1.0) * 100.0, 2)
    danger_level = "CRITICAL" if dd >= 30.0 else ("ELEVATED" if dd >= 15.0 else "SAFE")

    return {
        "current_drawdown_pct": round(dd, 2),
        "required_recovery_gain_pct": recovery_gain_pct,
        "absorbing_barrier_hit": False,
        "danger_level": danger_level,
        "asymmetry_multiplier": round(recovery_gain_pct / max(dd, 0.01), 2),
        "institutional_mandate": (
            f"A {dd:.1f}% drawdown requires a +{recovery_gain_pct:.1f}% net gain just to return to breakeven. "
            "Cutting losses quickly at 2% is not cowardice; it is mathematically mandatory for ergodicity."
        ),
    }
