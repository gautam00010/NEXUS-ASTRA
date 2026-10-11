"""Soros Reflexivity Engine (Primary IPO Paper Supply Overhang).

Mechanism:
- George Soros Reflexivity Principle:
  Market prices are not passive observers; they actively distort fundamental reality.
- Indian Market Reflexive Loop:
  1. Elevated valuations (Nifty P/E > 23x) entice promoters and PE funds to dump primary paper.
  2. Massive waves of IPOs, QIPs, and OFS (Offer For Sale) flood the Indian exchanges.
  3. Retail and institutional cash is absorbed into illiquid primary listings.
  4. Secondary market liquidity dries up -> earnings per share diluted -> structural market stagnation.
- Institutional Edge:
  When IPO pipeline exceeds ₹25,000 cr / month with elevated P/E, stand down broad market beta
  and rotate into idiosyncratic cash-flow generators.
"""

from __future__ import annotations
import logging
from typing import Any, Dict

logger = logging.getLogger(__name__)


def evaluate_soros_reflexivity_drag(
    nifty_pe: float = 23.8,
    monthly_primary_issuance_cr: float = 28500.0,  # ₹28,500 cr of IPOs/QIPs/OFS
    dii_monthly_sip_cr: float = 23000.0,            # ₹23,000 cr mutual fund SIP inflows
) -> Dict[str, Any]:
    """
    Evaluates reflexive liquidity drainage between primary paper supply and secondary cash inflows.
    """
    net_liquidity_drain_cr = monthly_primary_issuance_cr - dii_monthly_sip_cr
    paper_to_sip_ratio = round(monthly_primary_issuance_cr / max(dii_monthly_sip_cr, 1.0), 2)

    pe_stretched = nifty_pe >= 23.0
    supply_glut = paper_to_sip_ratio > 1.15

    if pe_stretched and supply_glut:
        phase = "EXCESS_PAPER_SUPPLY_OVERHANG"
        risk_level = "ELEVATED_STRUCTURAL_DRAG"
        beta_stance = "REDUCE_INDEX_BETA_TO_0.50"
        guidance = (
            f"NIFTY P/E is {nifty_pe:.1f}x and primary paper supply (₹{monthly_primary_issuance_cr:,.0f} cr) "
            f"exceeds monthly DII SIP inflows (₹{dii_monthly_sip_cr:,.0f} cr) by {paper_to_sip_ratio}x. "
            "Reflexive supply glut will compress index multiples. Reduce broad beta; focus on alpha."
        )
    elif not pe_stretched and not supply_glut:
        phase = "LIQUIDITY_SURPLUS_EXPANSION"
        risk_level = "FAVORABLE_TAILWIND"
        beta_stance = "FULL_BETA_DEPLOYMENT_1.0"
        guidance = (
            f"Primary paper issuance (₹{monthly_primary_issuance_cr:,.0f} cr) is easily absorbed by DII "
            f"SIP flows (₹{dii_monthly_sip_cr:,.0f} cr). Valuation {nifty_pe:.1f}x supports compounding."
        )
    else:
        phase = "BALANCED_REFLEXIVE_EQUILIBRIUM"
        risk_level = "MODERATE"
        beta_stance = "NORMAL_BETA_0.80"
        guidance = "Primary issuance balanced against secondary absorption. No structural liquidity bottleneck."

    return {
        "nifty_pe": round(nifty_pe, 2),
        "monthly_primary_issuance_cr": monthly_primary_issuance_cr,
        "dii_monthly_sip_cr": dii_monthly_sip_cr,
        "net_liquidity_drain_cr": net_liquidity_drain_cr,
        "paper_to_sip_ratio": paper_to_sip_ratio,
        "reflexivity_phase": phase,
        "risk_level": risk_level,
        "beta_stance": beta_stance,
        "guidance": guidance,
    }
