"""The Loser's Game & Unforced Errors Engine (Charles Ellis / Simon Ramo).

Principle:
- In amateur tennis and retail trading, matches are not won by hitting spectacular aces;
  they are lost by committing unforced errors (double faults, hitting into the net).
- SEBI Official Study (2024): 93% of individual F&O traders in India lose money, suffering
  an aggregate loss of ₹1.81 Lakh Crore, driven by:
  1. Overtrading: Trading every single day regardless of regime.
  2. Transaction Friction: Giving up massive edge to STT, exchange charges, and bid-ask spreads.
  3. Low-Conviction Noise: Forcing positions in 50/50 coin-flip conditions out of boredom.
- Institutional Edge (Top 2%):
  * Stand down and SKIP TRADING on 60%+ of trading sessions (150 out of 250 days a year).
  * Wait patiently like a sniper only for 4-star and 5-star institutional asymmetries.
  * Preserving capital is winning.
"""

from __future__ import annotations
import logging
from typing import Any, Dict

logger = logging.getLogger(__name__)


def evaluate_unforced_error_risk(
    setup_conviction_stars: int = 2,       # Scale of 1 to 5 stars
    market_volatility_clarity: str = "CHOP", # "TREND", "MEAN_REVERSION", "CHOP"
    consecutive_trades_today: int = 3,
    daily_pnl_inr: float = -4500.0,
) -> Dict[str, Any]:
    """
    Evaluates whether the trader is committing an unforced error.
    Enforces the 'Avoid 60% of Ambiguous Days' institutional discipline.
    """
    unforced_errors: list[str] = []

    # Check 1: Setup Quality Hurdle (Must be at least 4 stars)
    if setup_conviction_stars < 4:
        unforced_errors.append(f"LOW_QUALITY_SETUP_{setup_conviction_stars}_STARS (Must be >= 4 stars)")

    # Check 2: Market Structure Clarity
    if market_volatility_clarity == "CHOP":
        unforced_errors.append("AMBIGUOUS_CHOPPY_REGIME (No directional or stat-arb edge)")

    # Check 3: Overtrading / Revenge Trading
    if consecutive_trades_today >= 3 and daily_pnl_inr < 0:
        unforced_errors.append("POTENTIAL_REVENGE_TRADING (3+ trades executed with red P&L)")

    should_skip_trading = len(unforced_errors) > 0

    if should_skip_trading:
        decision = "STAND_DOWN_DO_NOT_TRADE"
        guidance = (
            f"Traded avoided to prevent unforced error. Reasons: {', '.join(unforced_errors)}. "
            "Institutional masters skip ~60% of trading sessions to wait for fat pitches."
        )
    else:
        decision = "EXECUTE_HIGH_CONVICTION_SETUP"
        guidance = (
            f"High-conviction {setup_conviction_stars}-star setup in clear {market_volatility_clarity} regime. "
            "Execution justified under strict Kelly risk control."
        )

    return {
        "decision": decision,
        "should_skip_trading": should_skip_trading,
        "setup_stars": setup_conviction_stars,
        "market_clarity": market_volatility_clarity,
        "consecutive_trades_today": consecutive_trades_today,
        "unforced_errors_detected": unforced_errors,
        "philosophy": (
            "Rule #1 of the Loser's Game: Don't beat yourself. Standing down on 60% of days "
            "eliminates 80% of retail transaction friction and drawdown."
        ),
        "guidance": guidance,
    }
