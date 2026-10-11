"""Model 9: Microstructure Spread Capture (BSE Smallcap Liquidity Provision).

Mechanism:
- In BSE Smallcaps and lower-tier liquid equities, the bid-ask spread widens to 1.0% to 2.5% (100-250 bps)
  during the morning opening hour (09:30 AM - 10:30 AM IST).
- Impatient retail traders dump or chase using market orders, forfeiting the full spread.
- Institutional / Prop Desk Edge:
  * Act as a passive liquidity provider by posting limit orders at the best bid and ask.
  * Time Window: Strictly 09:30 to 10:30 AM (after 09:15-09:30 open volatility settles, before mid-day stagnation).
  * Adverse Selection Protection: If order book queue imbalance > 3.5:1 on one side, cancel limit order
    immediately (do not stand in front of an institutional block iceberg order).
  * Inventory Rule: Zero overnight exposure; flatten inventory before 15:15 IST.
"""

from __future__ import annotations
import logging
from typing import Any, Dict

logger = logging.getLogger(__name__)


def evaluate_bse_liquidity_provision(
    symbol: str = "BSE_SMALLCAP_SELECTION",
    bid_price: float = 245.50,
    ask_price: float = 249.20,
    bid_depth_qty: int = 12000,
    ask_depth_qty: int = 11500,
    current_time_str: str = "09:45",
) -> Dict[str, Any]:
    """
    Evaluates passive limit spread capture opportunity on BSE Smallcap equities.
    Enforces time window (09:30 - 10:30 AM) and adverse selection imbalance filters.
    """
    mid_price = (bid_price + ask_price) / 2.0
    spread = ask_price - bid_price
    spread_pct = (spread / mid_price) * 100.0 if mid_price > 0 else 0.0
    spread_bps = spread_pct * 100.0

    # 1. Verify Time Window: 09:30 to 10:30 AM IST
    time_parts = current_time_str.split(":")
    hour, minute = int(time_parts[0]), int(time_parts[1]) if len(time_parts) > 1 else 0
    in_time_window = (hour == 9 and minute >= 30) or (hour == 10 and minute <= 30)

    # 2. Check Order Book Imbalance for Adverse Selection
    total_depth = bid_depth_qty + ask_depth_qty
    book_ratio = max(bid_depth_qty, ask_depth_qty) / max(1, min(bid_depth_qty, ask_depth_qty))
    adverse_selection = book_ratio > 3.5

    # 3. Check Minimum Spread Viability (1.0% to 2.5% spread)
    has_sufficient_spread = 1.0 <= spread_pct <= 2.5

    if in_time_window and has_sufficient_spread and not adverse_selection:
        action = "POST_PASSIVE_LIMIT_ORDERS"
        expected_capture_bps = round(spread_bps * 0.65, 1)  # Net spread after tick rebate & fees
        suggested_bid = round(bid_price + 0.05, 2)
        suggested_ask = round(ask_price - 0.05, 2)
        guidance = (
            f"Wide spread of {spread_pct:.2f}% ({spread_bps:.0f} bps) during prime window {current_time_str}. "
            f"Book is balanced (ratio {book_ratio:.1f}x). Post passive limit buy at ₹{suggested_bid} "
            f"and sell at ₹{suggested_ask}. Net capture ~{expected_capture_bps} bps."
        )
    elif adverse_selection:
        action = "STAND_DOWN_ADVERSE_SELECTION"
        expected_capture_bps = 0.0
        suggested_bid = 0.0
        suggested_ask = 0.0
        guidance = (
            f"Severe order book imbalance ({book_ratio:.1f}x). High probability of institutional block sweep. "
            "Canceling all passive orders to avoid being run over."
        )
    elif not in_time_window:
        action = "STAND_DOWN_OUTSIDE_WINDOW"
        expected_capture_bps = 0.0
        suggested_bid = 0.0
        suggested_ask = 0.0
        guidance = f"Current time {current_time_str} is outside the 09:30-10:30 AM morning spread capture window."
    else:
        action = "STAND_DOWN_SPREAD_TOO_TIGHT"
        expected_capture_bps = 0.0
        suggested_bid = 0.0
        suggested_ask = 0.0
        guidance = f"Spread {spread_pct:.2f}% ({spread_bps:.0f} bps) does not meet 1.0%-2.5% threshold for BSE liquidity provision."

    return {
        "model": "Model 9: Microstructure Spread Capture (BSE Smallcap)",
        "symbol": symbol,
        "current_time": current_time_str,
        "bid_price": bid_price,
        "ask_price": ask_price,
        "spread_pct": round(spread_pct, 2),
        "spread_bps": round(spread_bps, 1),
        "book_depth_ratio": round(book_ratio, 2),
        "in_time_window": in_time_window,
        "action": action,
        "suggested_bid_limit": suggested_bid,
        "suggested_ask_limit": suggested_ask,
        "expected_net_capture_bps": expected_capture_bps,
        "guidance": guidance,
    }
