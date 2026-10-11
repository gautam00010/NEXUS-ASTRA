"""Model 8: Volatility Risk Premium (VRP) Harvest (10-Delta Strangle).

Mechanism:
- Implied Volatility (IV) exceeds Realized Volatility (RV) in ~85% of trading environments
  due to structural hedging demand (investors paying an insurance premium).
- Institutional Execution Rules:
  * Harvest VRP by selling 10-delta OTM strangle (Nifty or BankNifty) 30 days out.
  * Delta hedge daily to maintain directional neutrality.
  * STRICT CONDITION: Active ONLY when India VIX > 20.0 (options premiums fat, high margin of safety).
    When VIX < 15, VRP harvesting is prohibited (pennies in front of steamroller risk).
  * Strict portfolio cap: Maximum 15.0% allocation / margin exposure to prevent tail-risk drawdown.
"""

from __future__ import annotations
import logging
from typing import Any, Dict

logger = logging.getLogger(__name__)


def evaluate_vrp_harvest(
    iv_30d_pct: float = 23.5,
    rv_30d_pct: float = 16.2,
    vix_current: float = 21.4,
    dte_target: int = 30,
    strangle_delta: float = 0.10,
    max_position_cap_pct: float = 15.0,
) -> Dict[str, Any]:
    """
    Evaluates whether Volatility Risk Premium harvest conditions are met.
    Enforces VIX > 20 filter and max 15% position allocation limit.
    """
    vrp_spread = iv_30d_pct - rv_30d_pct
    vrp_ratio = iv_30d_pct / rv_30d_pct if rv_30d_pct > 0 else 1.0

    # Safety Guard 1: Must have positive VRP spread (IV > RV)
    has_premium_edge = vrp_spread >= 3.0  # At least 3 vol points gap

    # Safety Guard 2: Absolute VIX Filter (VIX > 20)
    vix_hurdle_passed = vix_current >= 20.0

    if has_premium_edge and vix_hurdle_passed:
        status = "EXECUTE_VRP_HARVEST"
        # Scale allocation proportional to VRP ratio, capped strictly at 15.0%
        raw_alloc = min(max_position_cap_pct, round(5.0 * vrp_ratio, 2))
        recommended_allocation_pct = min(raw_alloc, max_position_cap_pct)
        strategy = f"Sell {int(strangle_delta * 100)}Δ Call + {int(strangle_delta * 100)}Δ Put ({dte_target} DTE)"
        delta_hedge_rule = "Rebalance delta when net portfolio delta drifts > ±0.15 using Nifty futures."
        rationale = (
            f"VIX is {vix_current:.1f} (> 20.0 hurdle) and IV ({iv_30d_pct:.1f}%) exceeds RV ({rv_30d_pct:.1f}%) "
            f"by +{vrp_spread:.1f} vol points (VRP ratio: {vrp_ratio:.2f}x). Harvest fat insurance premium "
            f"with strict {recommended_allocation_pct:.1f}% position cap and daily delta hedging."
        )
    elif not vix_hurdle_passed:
        status = "STAND_DOWN_VIX_TOO_LOW"
        recommended_allocation_pct = 0.0
        strategy = "NO_SHORT_GAMMA_POSITION"
        delta_hedge_rule = "N/A"
        rationale = (
            f"Current VIX {vix_current:.1f} is BELOW required 20.0 hurdle. Selling low-vol options generates "
            "negligible yield while exposing capital to asymmetric tail blowout. Prohibited."
        )
    else:
        status = "STAND_DOWN_NO_VRP_EDGE"
        recommended_allocation_pct = 0.0
        strategy = "NO_SHORT_GAMMA_POSITION"
        delta_hedge_rule = "N/A"
        rationale = f"IV ({iv_30d_pct:.1f}%) does not sufficiently exceed RV ({rv_30d_pct:.1f}%). Spread {vrp_spread:.1f} vol pts is inadequate."

    return {
        "model": "Model 8: Volatility Risk Premium (VRP) Harvest Strangle",
        "vix_current": round(vix_current, 2),
        "vix_hurdle_met": vix_hurdle_passed,
        "iv_30d_pct": round(iv_30d_pct, 2),
        "rv_30d_pct": round(rv_30d_pct, 2),
        "vrp_spread_vol_pts": round(vrp_spread, 2),
        "vrp_ratio": round(vrp_ratio, 2),
        "status": status,
        "strategy": strategy,
        "target_delta": strangle_delta,
        "target_dte": dte_target,
        "recommended_allocation_pct": recommended_allocation_pct,
        "max_cap_pct": max_position_cap_pct,
        "delta_hedge_rule": delta_hedge_rule,
        "rationale": rationale,
    }
