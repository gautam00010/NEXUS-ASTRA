"""Expected Value (EV) Engine with Indian F&O / Equity Transaction Friction.

Mathematical Definition:
  Gross EV = (P_win * Avg_Win) - (P_loss * Avg_Loss)
  Net EV   = Gross EV - Friction_Costs (STT, Stamp Duty, GST, Exchange charges, Slippage)

Rule:
- If Net EV <= 0.0 -> HARD SKIP / DON'T_TRADE. Zero edge after friction.
- Breakeven Win Rate:
    P_be = (Avg_Loss + Friction) / (Avg_Win + Avg_Loss)
"""

from __future__ import annotations
import logging
from typing import Any, Dict

logger = logging.getLogger(__name__)


def calculate_trade_expected_value(
    win_rate: float = 0.52,             # 52% probability of win
    avg_win_inr: float = 24000.0,       # Average winning trade
    avg_loss_inr: float = 12000.0,      # Average losing trade (1:2 RR)
    capital_at_risk_inr: float = 12000.0,
    roundtrip_friction_inr: float = 650.0,  # STT + Stamp Duty + Brokerage + Slippage
    trades_per_year: int = 250,
) -> Dict[str, Any]:
    """
    Computes rigorous Expected Value per trade and annualized mathematical expectation.
    """
    if not (0.0 < win_rate < 1.0):
        raise ValueError("win_rate must be between 0 and 1 exclusive")
    if avg_win_inr <= 0 or avg_loss_inr <= 0:
        raise ValueError("avg_win_inr and avg_loss_inr must be positive")

    loss_rate = 1.0 - win_rate
    gross_ev = (win_rate * avg_win_inr) - (loss_rate * avg_loss_inr)
    net_ev = gross_ev - roundtrip_friction_inr

    # Breakeven win rate with friction
    be_win_rate = (avg_loss_inr + roundtrip_friction_inr) / (avg_win_inr + avg_loss_inr)

    # EV per rupee risked
    ev_per_rupee_risked = net_ev / capital_at_risk_inr if capital_at_risk_inr > 0 else 0.0

    # Annual expected return from this strategy
    annual_expected_pnl = net_ev * trades_per_year

    status = "TRADEABLE_POSITIVE_EDGE" if net_ev > 0 else "REJECT_NEGATIVE_EV"

    return {
        "status": status,
        "win_rate_pct": round(win_rate * 100.0, 2),
        "breakeven_win_rate_pct": round(be_win_rate * 100.0, 2),
        "edge_over_breakeven_pct": round((win_rate - be_win_rate) * 100.0, 2),
        "gross_ev_inr": round(gross_ev, 2),
        "friction_cost_inr": round(roundtrip_friction_inr, 2),
        "net_ev_per_trade_inr": round(net_ev, 2),
        "ev_per_rupee_risked": round(ev_per_rupee_risked, 4),
        "trades_per_year": trades_per_year,
        "annual_expected_pnl_inr": round(annual_expected_pnl, 2),
        "recommendation": (
            f"Net EV is +₹{net_ev:,.2f} per trade after STT/slippage. Edge over breakeven: "
            f"+{(win_rate - be_win_rate)*100:.2f}%. Annualized EV across {trades_per_year} trades: "
            f"+₹{annual_expected_pnl:,.2f}." if net_ev > 0 else
            f"Net EV is -₹{abs(net_ev):,.2f} per trade after friction. Breakeven requires {be_win_rate*100:.1f}% "
            "win rate. DO NOT TRADE."
        ),
    }
