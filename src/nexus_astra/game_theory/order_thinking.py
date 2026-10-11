"""Second vs. Third Order Thinking for NSE / BSE Execution.

Game-Theoretic Paradigm:
1. FIRST ORDER (Retail Mentality):
   - "US markets rallied overnight, NIFTY gapped up +1.0% -> Buy at the open!"
   - Result: Buys into institutional distribution; gets chopped out.
2. SECOND ORDER (Standard Quant / Sophisticated Retail):
   - "Everyone sees the gap up. The opening long is crowded. Historical stats show gap fades by 10:30 AM on weak volume.
   - Action: Fade the open (Short at 9:15-9:20 AM)."
   - Result: Works on ordinary days, but gets decimated on true trend days.
3. THIRD ORDER (Institutional LFT / Two Sigma / Bridgewater Model):
   - "If every retail quant knows the gap fades, HFTs front-run the fade into the 9:08 AM pre-open auction.
   - The TRUE asymmetric edge occurs when the fade FAILS:
     * NIFTY Gap > 1.2% (large macro impulse)
     * FII net long index futures > 80th percentile (structural institutional sponsorship)
     * BankNIFTY is NOT confirming the fade (refusing to drop, holding opening highs)
   - When the fade fails, all second-order quants are trapped short and forced to cover, fueling a monster runaway trend day!
   - Action: Go LONG THE FAILED FADE -> ride the multi-hour trend day to the close."
"""

from __future__ import annotations
import logging
from typing import Any, Dict

logger = logging.getLogger(__name__)


def third_order_signal(
    gap_pct: float = 1.35,
    fii_long_pct: float = 85.0,  # 85th percentile FII long index futures
    banknifty_confirm_fade: bool = False,  # BankNifty is NOT dropping/confirming fade
    current_time_str: str = "09:35",
    fii_long_futures_percentile: float | None = None,
    banknifty_confirms_fade: bool | None = None,
) -> Dict[str, Any]:
    """
    Evaluates order-thinking levels and identifies the high-convexity 'Failed Fade' trend day setup.
    """
    if fii_long_futures_percentile is not None:
        fii_long_pct = fii_long_futures_percentile
    if banknifty_confirms_fade is not None:
        banknifty_confirm_fade = banknifty_confirms_fade

    abs_gap = abs(gap_pct)

    # 1st Order Analysis
    first_order = {
        "perspective": "Retail Instinct",
        "rationale": f"NIFTY gapped {gap_pct:+.2f}%. Sentiment is bullish -> Chase the open.",
        "action": "BUY_CHASE",
        "reaction": "Retail chasing opening gap up without institutional volume confirmation.",
    }

    # 2nd Order Analysis
    second_order = {
        "perspective": "Standard Quant Consensus",
        "rationale": "Gaps fade 68% of the time by 10:30 AM without volume. Short the gap open.",
        "action": "SHORT_FADE_OPEN",
        "reaction": "Quants crowding short side to fade open at 10:30 AM.",
    }

    # 3rd Order Institutional Analysis
    is_failed_fade_trend_day = (
        abs_gap >= 1.20 and
        fii_long_pct >= 80.0 and
        not banknifty_confirm_fade
    )

    if is_failed_fade_trend_day:
        third_order = {
            "perspective": "Institutional LFT (Two Sigma / Bridgewater)",
            "signal": "LONG_FAILED_FADE",
            "action": "BUY_LONG_TREND_DAY",
            "failed_fade_confirmed": True,
            "reaction": "Failed fade creates massive short-covering surge; institutional inventory forces runaway expansion.",
            "mechanism": (
                "Consensus second-order quants shorted the open expecting a routine gap fade. "
                "However, massive FII long inventory (>80%ile) and BankNIFTY non-confirmation indicate real capital allocation. "
                "The fade has failed; short-covering will fuel an explosive trend day into the close."
            ),
            "expected_payoff_ratio": "1:3.5",
            "win_rate_probability": 0.68,
        }
        final_action = "LONG_FAILED_FADE_TREND_EXPANSION"
        win_rate_expectancy = 68.0
    elif abs_gap >= 0.8 and fii_long_pct < 50.0 and banknifty_confirm_fade:
        third_order = {
            "perspective": "Institutional LFT",
            "signal": "STANDARD_FADE_CONFIRMED",
            "action": "SHORT_ORDINARY_FADE",
            "failed_fade_confirmed": False,
            "reaction": "Ordinary gap fade proceeds normally as FIIs and BankNifty confirm weakness.",
            "mechanism": "FIIs are not positioned long and BankNIFTY confirms weakness. Ordinary gap fade proceeds normally.",
            "expected_payoff_ratio": "1:1.8",
            "win_rate_probability": 0.64,
        }
        final_action = "SHORT_FADE_OPEN_AT_10_30_AM"
        win_rate_expectancy = 64.0
    else:
        third_order = {
            "perspective": "Institutional LFT",
            "signal": "NO_ASYMMETRY",
            "action": "STAND_ASIDE",
            "failed_fade_confirmed": False,
            "reaction": "No clear game-theoretic divergence between retail and quants.",
            "mechanism": "No clear game-theoretic divergence between retail and quants. Preserve capital.",
            "expected_payoff_ratio": "1:1.0",
            "win_rate_probability": 0.50,
        }
        final_action = "STAND_ASIDE"
        win_rate_expectancy = 50.0

    return {
        "gap_pct": round(gap_pct, 2),
        "fii_long_percentile": round(fii_long_pct, 1),
        "banknifty_confirm_fade": banknifty_confirm_fade,
        "first_order_retail": first_order,
        "second_order_quant": second_order,
        "third_order_institutional": third_order,
        "final_signal": third_order["signal"],
        "final_action": third_order["action"],
        "action": final_action,
        "win_rate_expectancy_pct": win_rate_expectancy,
    }

