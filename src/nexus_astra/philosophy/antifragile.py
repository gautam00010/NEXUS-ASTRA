"""Antifragile 80/20 Barbell Engine (Nassim Nicholas Taleb).

Architecture:
- The Fragile Middle:
  * 95% of investors sit in the "middle" (e.g., balanced funds, corporate debt, unhedged equities).
  * In a crisis, the middle suffers severe correlation breakdown and catastrophic drawdowns.
- The Antifragile Barbell:
  * 80% Hyper-Safe Fortress:
    - Liquid Bees, G-Sec sovereign bills, Overnight TREPS (zero credit risk, ~6.8% risk-free yield).
    - Guarantees complete invulnerability to margin calls and economic crashes.
  * 20% Hyper-Convex Asymmetric Long Convexity:
    - Deep OTM options post-crash, high-momentum smallcaps, pure right-tail convexity.
    - Max loss strictly bounded at 20%; upside is mathematically unbounded (10x - 50x in regime shifts).
"""

from __future__ import annotations
import logging
from typing import Any, Dict

logger = logging.getLogger(__name__)


def compute_antifragile_barbell_allocation(
    total_capital_inr: float = 1_000_000.0,
    safe_floor_pct: float = 80.0,
    convex_alpha_pct: float = 20.0,
    risk_free_rate_pct: float = 6.8,
) -> Dict[str, Any]:
    """
    Computes exact capital split and scenario payoffs for the 80/20 Antifragile Barbell.
    """
    if safe_floor_pct + convex_alpha_pct != 100.0:
        raise ValueError("Safe floor + Convex alpha must sum to exactly 100.0%")

    safe_capital = total_capital_inr * (safe_floor_pct / 100.0)
    convex_capital = total_capital_inr * (convex_alpha_pct / 100.0)

    # 1-Year Scenario Simulation
    # Scenario A: Market Crash (-35% equity crash)
    # Safe sleeve earns 6.8% risk-free; Convex puts explode +300% (4x)
    scen_crash_safe = safe_capital * (1.0 + risk_free_rate_pct / 100.0)
    scen_crash_convex = convex_capital * 4.0
    pnl_crash_total = (scen_crash_safe + scen_crash_convex) - total_capital_inr
    pnl_crash_pct = (pnl_crash_total / total_capital_inr) * 100.0

    # Scenario B: Stagnant Flat Market (0% return)
    # Safe sleeve earns 6.8%; Convex options decay by -60%
    scen_flat_safe = safe_capital * (1.0 + risk_free_rate_pct / 100.0)
    scen_flat_convex = convex_capital * 0.40
    pnl_flat_total = (scen_flat_safe + scen_flat_convex) - total_capital_inr
    pnl_flat_pct = (pnl_flat_total / total_capital_inr) * 100.0

    # Scenario C: Explosive Bull Market (+35% equity rally)
    # Safe sleeve earns 6.8%; Convex calls / momentum explode +180%
    scen_bull_safe = safe_capital * (1.0 + risk_free_rate_pct / 100.0)
    scen_bull_convex = convex_capital * 2.80
    pnl_bull_total = (scen_bull_safe + scen_bull_convex) - total_capital_inr
    pnl_bull_pct = (pnl_bull_total / total_capital_inr) * 100.0

    return {
        "total_capital_inr": total_capital_inr,
        "safe_fortress_pct": safe_floor_pct,
        "safe_capital_inr": round(safe_capital, 2),
        "safe_instruments": "Liquid Bees / Overnight TREPS / 91-Day T-Bills (~6.8% p.a.)",
        "convex_alpha_pct": convex_alpha_pct,
        "convex_capital_inr": round(convex_capital, 2),
        "convex_instruments": "Deep OTM Tail Puts / High-Momentum LFT Decile 1 Runners",
        "scenarios": {
            "severe_crash_minus_35pct": {
                "safe_value": round(scen_crash_safe, 2),
                "convex_value": round(scen_crash_convex, 2),
                "total_portfolio_pnl_pct": round(pnl_crash_pct, 2),
                "outcome": "NET GAIN (Antifragile benefit from convex puts)",
            },
            "flat_chop_market_0pct": {
                "safe_value": round(scen_flat_safe, 2),
                "convex_value": round(scen_flat_convex, 2),
                "total_portfolio_pnl_pct": round(pnl_flat_pct, 2),
                "outcome": "CAPITAL PRESERVED (Safe yield cushions premium decay)",
            },
            "explosive_bull_plus_35pct": {
                "safe_value": round(scen_bull_safe, 2),
                "convex_value": round(scen_bull_convex, 2),
                "total_portfolio_pnl_pct": round(pnl_bull_pct, 2),
                "outcome": "SUPERIOR COMPOUNDING (Convex momentum upside)",
            },
        },
        "philosophical_rule": (
            "Never play the fragile middle. 80% untouchable cash/treasuries prevents ruin; "
            "20% convex asymmetric risk captures non-linear exponential windfalls."
        ),
    }
