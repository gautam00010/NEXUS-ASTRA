"""Game Theory & Structural Edge vs HFT / AI for Institutional LFT.

Core Principles:
1. CAPACITY CONSTRAINTS:
   - High-Frequency Trading (HFT) firms and market makers operate under ultra-tight overnight risk models.
   - HFTs CANNOT carry ₹50 Crore inventory overnight due to exchange margin haircuts, internal VaR limits,
     and overnight gap jump risk.
   - Low-Frequency Trading (LFT) with multiday holding periods has the structural capacity to absorb multi-day flow.
2. SLOW ALPHA:
   - Deep fundamental alpha takes 3 to 10 trading days to fully price into equity markets.
   - Examples: Persistent Foreign Institutional Investor (FII) index futures positioning, RBI monetary policy
     transmission into bank net interest margins (NIM), and post-earnings analyst consensus drift.
   - Order-book machine learning and 1-second predictive AI trained on tick prices completely miss slow alpha.
3. CROWDING PAIN & SECOND-ORDER EV:
   - When retail and consensus quants pile into the same obvious trade, the price can still tick up in the ultra-short term
     (first-order momentum), but Expected Value (EV) collapses (second-order).
   - Any negative shock induces a violent liquidity cascade where crowded longs rush for the exit.
"""

from __future__ import annotations
import logging
from typing import Any, Dict, List

logger = logging.getLogger(__name__)

EDGE_TAXONOMY: Dict[str, Dict[str, Any]] = {
    "CAPACITY_ADVANTAGE": {
        "name": "Overnight Multi-Day Inventory Capacity",
        "mechanism": "Carrying positions across 3-15 days where HFT intraday risk models cannot hold inventory.",
        "edge_durability": "High - HFTs are architecturally barred from multi-day capital tie-up.",
    },
    "SLOW_ALPHA_TRANSMISSION": {
        "name": "Macro & Fundamental Transmission Lag",
        "mechanism": "Exploiting 3-10 day diffusion of institutional FII flow, RBI policy, and analyst earnings revisions.",
        "edge_durability": "High - Order-book AI models are blind to multiday macro information diffusion.",
    },
    "LIQUIDITY_PROVISION_UNTOUCHED": {
        "name": "Niche Capacity Liquidity Provision",
        "mechanism": "Providing two-sided liquidity in low-capacity midcap/smallcap spreads (1-2%) ignored by large algos.",
        "edge_durability": "Medium - Sustainable below ₹5-10 Crore AUM.",
    },
    "FAILED_CONSENSUS_CONVEXITY": {
        "name": "Third-Order Crowded Trade Exploitation",
        "mechanism": "Fading the consensus fade when structural institutional volume overrides retail and quant consensus.",
        "edge_durability": "Very High - Profits directly from the liquidation of crowded quants.",
    },
}


def explicit_edge_vs_hft(
    holding_horizon: str = "MULTI_DAY",
    has_slow_alpha: bool = True,
    is_crowded: bool = False,
    capital_under_management_cr: float = 5.0,
    edge_type: str = "SLOW_ALPHA_TRANSMISSION",
    holding_period_days: int | None = None,
    capital_deployed_cr: float | None = None,
) -> Dict[str, Any]:
    """
    Evaluates whether an LFT strategy has a defensible mathematical edge against HFT algorithms.
    If no explicit structural edge exists, returns DON'T_TRADE.
    """
    if holding_period_days is not None:
        if holding_period_days <= 0:
            holding_horizon = "SUB_SECOND"
        elif holding_period_days >= 3:
            holding_horizon = "MULTI_DAY"
        else:
            holding_horizon = "INTRADAY"

    if capital_deployed_cr is not None:
        capital_under_management_cr = capital_deployed_cr

    # Rule 1: Intraday sub-minute scalping against HFTs has zero edge
    if holding_horizon in ["TICK", "SUB_MINUTE", "MILLISECOND", "SUB_SECOND"]:
        return {
            "status": "DONT_TRADE",
            "decision": "DON'T_TRADE",
            "edge_exists": False,
            "holding_horizon": "SUB_SECOND_LATENCY",
            "edge_classification": "NONE",
            "reason": "Sub-minute trading directly competes with microwave/co-located HFT latency. Zero structural edge.",
            "recommended_action": "ABORT_TRADE",
            "guidance": "Sub-second trading directly competes with microwave/co-located HFT latency. Zero structural edge.",
        }

    # Rule 2: Trade is highly crowded without convexity
    if is_crowded and edge_type not in ["FAILED_CONSENSUS_CONVEXITY"]:
        return {
            "status": "DONT_TRADE",
            "decision": "DON'T_TRADE",
            "edge_exists": False,
            "holding_horizon": holding_horizon,
            "edge_classification": "CROWDED_NO_EDGE",
            "reason": "Trade is crowded by consensus retail/quants. Expected value (EV) collapsed due to exit liquidity risk.",
            "recommended_action": "WAIT_FOR_LIQUIDATION_SHOCK",
            "guidance": "Trade is crowded by consensus retail/quants. Exit liquidity risk collapses EV.",
        }

    # Rule 3: Must exhibit valid LFT edge category
    if edge_type not in EDGE_TAXONOMY:
        return {
            "status": "DONT_TRADE",
            "decision": "DON'T_TRADE",
            "edge_exists": False,
            "holding_horizon": holding_horizon,
            "edge_classification": "UNCLASSIFIED",
            "reason": "No validated structural edge category specified. Pure gambling without game-theoretic justification.",
            "recommended_action": "REVISE_THESIS",
            "guidance": "No validated structural edge category specified.",
        }

    edge_info = EDGE_TAXONOMY[edge_type]
    return {
        "status": "APPROVED_STRUCTURAL_EDGE",
        "decision": "PROCEED_LFT_EXECUTION",
        "edge_exists": True,
        "edge_classification": "SLOW_ALPHA_MACRO_FLOW",
        "edge_category": edge_type,
        "name": edge_info["name"],
        "mechanism": edge_info["mechanism"],
        "durability": edge_info["edge_durability"],
        "holding_horizon": holding_horizon,
        "guidance": "HFT speed advantage eliminated; playing in the multi-day slow-alpha domain where capacity constraints protect our edge.",
        "hft_neutralization": "HFT speed advantage eliminated; playing in the multi-day slow-alpha domain where capacity constraints protect our edge.",
    }

