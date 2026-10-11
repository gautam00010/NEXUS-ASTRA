"""Cognitive Bias Detection & P&L Preservation Engine for Indian & Crypto Traders.

Detects the 5 fatal cognitive biases that destroy 95% of retail accounts:
1. DISPOSITION EFFECT: Booking small +2% profits fast while holding -10% losers. Fix SL before entry.
2. OVERNIGHT RISK BIAS: Holding intraday losers overnight hoping for a gap up; gap risk is 3x intraday.
3. RECENCY BIAS: Assuming 3 green days guarantee a 4th green day; Nifty mean-reverts after 2-3 days.
4. LOTTERY BIAS: Buying BSE SME / penny stocks (₹5 to ₹100); 93% underperform Nifty over 5 years.
5. ANCHORING BIAS: Anchoring to nominal price peaks (TCS 4000 -> 3500 "looks cheap"); prices have no memory.
"""

from __future__ import annotations
import logging
from typing import Any, Dict, List

logger = logging.getLogger(__name__)

BIAS_DEFINITIONS: Dict[str, Dict[str, Any]] = {
    "DISPOSITION_EFFECT": {
        "name": "Disposition Effect (Asymmetric Loss Holding)",
        "mechanism": "Booking tiny +2% profits prematurely while refusing to cut -10% losers due to loss aversion.",
        "pnl_impact": "Generates a severe negative expectancy with tiny average wins and massive tail losses.",
        "quant_cure": "Pre-set hard Stop-Loss (1.5x ATR) and Take-Profit (+2R) BEFORE order submission. Automated execution.",
    },
    "OVERNIGHT_RISK_BIAS": {
        "name": "Overnight Loser Bias (Carrying Hope)",
        "mechanism": "Converting a failed intraday trade into an overnight swing, praying for a gap-up opening.",
        "pnl_impact": "Overnight gap risk is 3x intraday standard deviation. Exposes capital to unhedgeable jump risk.",
        "quant_cure": "Strict 3:15 PM IST intraday hard square-off. No intraday trade may ever be held overnight.",
    },
    "RECENCY_BIAS": {
        "name": "Recency Bias (Streak Extrapolation)",
        "mechanism": "Assuming that after 3 consecutive green days, the 4th day is guaranteed green, doubling position size.",
        "pnl_impact": "NIFTY exhibits strong mean-reversion after 2-3 consecutive trend days. Buying day 4 buys the top.",
        "quant_cure": "Scale down position sizing by 50% after 3 consecutive trend days. Anticipate mean-reversion.",
    },
    "LOTTERY_BIAS": {
        "name": "Lottery Bias (Penny Stock / BSE SME Chasing)",
        "mechanism": "Purchasing illiquid ₹5 to ₹100 penny stocks hoping for a 10x multibagger jackpot.",
        "pnl_impact": "Empirical study: 93% of Indian microcaps and BSE SME stocks underperform NIFTY 50 over 5 years.",
        "quant_cure": "Strict universe filtering: trade exclusively NIFTY 50 / F&O securities with >₹500 Cr daily volume.",
    },
    "ANCHORING_BIAS": {
        "name": "Anchoring Bias (Nominal Peak Fallacy)",
        "mechanism": "Assuming a stock is 'cheap' because it fell from ₹4,000 to ₹3,500 (e.g. TCS or Tech stocks).",
        "pnl_impact": "Stock prices have zero memory of where they traded yesterday. Downward momentum often accelerates.",
        "quant_cure": "Base decisions exclusively on forward valuation multiples, earnings revisions, and quantitative momentum.",
    },
}


def check_disposition_effect(
    current_pnl_pct: float,
    holding_duration_mins: int,
    is_winning_cut_early: bool = False,
    is_loser_extended: bool = False,
) -> Dict[str, Any]:
    """Flag disposition effect if booking tiny profit early or letting loss run past threshold."""
    triggered = False
    alert_msg = "OK"

    if current_pnl_pct <= -5.0:
        triggered = True
        alert_msg = f"CRITICAL: Position down {current_pnl_pct:.1f}% without stop-loss execution! Disposition effect active."
    elif current_pnl_pct >= 1.5 and is_winning_cut_early:
        triggered = True
        alert_msg = f"WARNING: Cutting small profit (+{current_pnl_pct:.1f}%) prematurely before 2R target is reached."

    return {
        "bias": "DISPOSITION_EFFECT",
        "triggered": triggered,
        "alert": alert_msg,
        "recommendation": BIAS_DEFINITIONS["DISPOSITION_EFFECT"]["quant_cure"],
    }


def check_overnight_risk_bias(
    is_intraday_strategy: bool,
    current_time_str: str,
    position_pnl_pct: float,
    holding_overnight: bool,
) -> Dict[str, Any]:
    """Flag holding a losing intraday position overnight."""
    triggered = False
    alert_msg = "OK"

    if is_intraday_strategy and holding_overnight and position_pnl_pct < 0:
        triggered = True
        alert_msg = (
            f"FATAL RISK: Holding losing intraday trade ({position_pnl_pct:.1f}%) overnight into closing cross! "
            "Gap risk is 3x intraday. Mandatory square-off at 3:15 PM!"
        )

    return {
        "bias": "OVERNIGHT_RISK_BIAS",
        "triggered": triggered,
        "alert": alert_msg,
        "recommendation": BIAS_DEFINITIONS["OVERNIGHT_RISK_BIAS"]["quant_cure"],
    }


def check_recency_bias(consecutive_green_days: int) -> Dict[str, Any]:
    """Flag streak extrapolation after 3+ consecutive green sessions."""
    triggered = consecutive_green_days >= 3
    alert_msg = (
        f"CAUTION: NIFTY has closed green {consecutive_green_days} consecutive days. "
        "Recency bias risk: mean-reversion probability is elevated. Do NOT increase leverage."
        if triggered
        else "Normal regime: streak < 3 days."
    )
    return {
        "bias": "RECENCY_BIAS",
        "triggered": triggered,
        "streak_days": consecutive_green_days,
        "alert": alert_msg,
        "recommendation": BIAS_DEFINITIONS["RECENCY_BIAS"]["quant_cure"],
    }


def check_lottery_bias(stock_price: float, is_sme: bool = False) -> Dict[str, Any]:
    """Flag trading low-priced microcaps / BSE SME penny stocks."""
    triggered = bool(stock_price < 50.0 or is_sme)
    alert_msg = (
        f"LOTTERY BIAS ALERT: Asset price ₹{stock_price:.1f} is a penny/SME stock. "
        "93% underperform Nifty over 5 years. Avoid gambling."
        if triggered
        else "Universe filter passed: standard liquid security."
    )
    return {
        "bias": "LOTTERY_BIAS",
        "triggered": triggered,
        "alert": alert_msg,
        "recommendation": BIAS_DEFINITIONS["LOTTERY_BIAS"]["quant_cure"],
    }


def check_anchoring_bias(nominal_drop_pct: float, earnings_momentum_pct: float) -> Dict[str, Any]:
    """Flag anchoring to price drop when fundamentals or momentum are weak."""
    triggered = nominal_drop_pct >= 15.0 and earnings_momentum_pct < 0
    alert_msg = (
        f"ANCHORING WARNING: Stock dropped {nominal_drop_pct:.1f}% from peak, but fundamentals are negative. "
        "Do NOT anchor to previous highs. Price has zero memory."
        if triggered
        else "Valuation analysis validated."
    )
    return {
        "bias": "ANCHORING_BIAS",
        "triggered": triggered,
        "alert": alert_msg,
        "recommendation": BIAS_DEFINITIONS["ANCHORING_BIAS"]["quant_cure"],
    }


def evaluate_trader_biases(
    trade_state: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    """
    Evaluates comprehensive trader cognitive health across all 5 fatal biases.
    """
    if trade_state is None:
        trade_state = {
            "current_pnl_pct": -6.2,
            "holding_duration_mins": 180,
            "is_intraday": True,
            "holding_overnight": True,
            "current_time_str": "15:20",
            "consecutive_green_days": 3,
            "stock_price": 28.5,
            "is_sme": False,
            "nominal_drop_pct": 22.0,
            "earnings_momentum_pct": -4.0,
        }

    b1 = check_disposition_effect(
        trade_state.get("current_pnl_pct", 0.0),
        trade_state.get("holding_duration_mins", 0),
        is_loser_extended=trade_state.get("current_pnl_pct", 0.0) < -5.0,
    )
    b2 = check_overnight_risk_bias(
        trade_state.get("is_intraday", True),
        trade_state.get("current_time_str", "15:20"),
        trade_state.get("current_pnl_pct", 0.0),
        trade_state.get("holding_overnight", False),
    )
    b3 = check_recency_bias(trade_state.get("consecutive_green_days", 1))
    b4 = check_lottery_bias(
        trade_state.get("stock_price", 100.0),
        trade_state.get("is_sme", False),
    )
    b5 = check_anchoring_bias(
        trade_state.get("nominal_drop_pct", 0.0),
        trade_state.get("earnings_momentum_pct", 0.0),
    )

    alerts = [b for b in [b1, b2, b3, b4, b5] if b["triggered"]]
    active_count = len(alerts)

    return {
        "active_biases_count": active_count,
        "account_health": "CRITICAL_RISK" if active_count >= 2 else ("WARNING" if active_count == 1 else "DISCIPLINED"),
        "biases": {
            "disposition_effect": b1,
            "overnight_risk_bias": b2,
            "recency_bias": b3,
            "lottery_bias": b4,
            "anchoring_bias": b5,
        },
        "critical_summary": (
            "🚨 CRITICAL BIAS DETECTED: Cut losing trades before 3:15 PM; avoid holding overnight losers or penny stocks!"
            if active_count > 0
            else "✅ Trader psychology clean: adhering to algorithmic discipline."
        ),
    }
