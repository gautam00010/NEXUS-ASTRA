"""NSE / BSE Market Microstructure and Session Dynamics.

Key Timings on the National Stock Exchange of India (NSE):
1. Pre-Open Auction (9:00 AM - 9:15 AM IST):
   - 9:00 to 9:08 AM: Order entry, modification, cancellation.
   - 9:08 to 9:12 AM: Call auction equilibrium price discovery (order matching).
   - ~80% of overnight gap pricing settles here before continuous trading begins.
2. First 30 Minutes (9:15 AM - 9:45 AM IST):
   - Institutional flow dominates: FIIs, DIIs, prop trading desks executing TWAP/VWAP blocks.
   - Opening Range Breakout (ORB) establishes daily high/low bias.
3. Mid-Day Consolidation (10:30 AM - 2:00 PM IST):
   - Volume dries up; European market open at 1:00 PM IST provides secondary volatility.
4. Final 30 Minutes (3:00 PM - 3:30 PM IST):
   - Retail & broker auto-square-off of intraday margin (MIS) trades (3:15 PM - 3:20 PM).
   - Severe short-covering squeezes or liquidity distribution.
"""

from __future__ import annotations
from datetime import datetime, time
import logging
from typing import Any, Dict

logger = logging.getLogger(__name__)

NSE_SESSIONS: Dict[str, Dict[str, Any]] = {
    "PRE_OPEN": {
        "start": time(9, 0),
        "end": time(9, 15),
        "name": "Pre-Open Call Auction",
        "primary_actors": "Institutions, HFT Arbitrageurs, Market Makers",
        "phenomenon": (
            "80% of overnight price repricing occurs here via the uncrossing equilibrium algorithm. "
            "No retail execution; pure information assimilation from US/Asian overnight sessions."
        ),
        "quant_guidance": "Observe equilibrium price vs yesterday close. Do not place aggressive market orders.",
    },
    "INSTITUTIONAL_OPEN": {
        "start": time(9, 15),
        "end": time(9, 45),
        "name": "First 30 Mins (Institutional Price Discovery)",
        "primary_actors": "Foreign Institutional Investors (FII), DII Mutual Funds, Algorithmic Desks",
        "phenomenon": (
            "Peak volume velocity and true trend emergence. Opening Range Breakout (9:15-9:30) "
            "establishes the directional trajectory for 70% of trending days."
        ),
        "quant_guidance": "Mark 15-min ORB High and Low. Enter only after 9:30 AM on volume breakout confirmation.",
    },
    "MIDDAY_LULL": {
        "start": time(9, 45),
        "end": time(14, 30),
        "name": "Mid-Day Mean-Reversion / European Open",
        "primary_actors": "Market Makers, Retail Day Traders, European Flow (at 1:00 PM IST)",
        "phenomenon": (
            "Trend dissipation; chop and VWAP mean-reversion dominate. False breakouts frequent."
        ),
        "quant_guidance": "Avoid buying new breakouts. Trade VWAP +/- 2 std dev mean-reversion only on large caps.",
    },
    "EXPIRY_POWER_HOUR": {
        "start": time(14, 30),
        "end": time(15, 0),
        "name": "0DTE Expiry Acceleration / Thursday Power Hour",
        "primary_actors": "Options Writers, Gamma Scalpers, Institutional Rebalancers",
        "phenomenon": (
            "Accelerated theta decay on 0DTE weekly options. Strangles and iron condors burn premium fastest."
        ),
        "quant_guidance": "Sell far OTM 1.5% strangles at 2:30 PM with hard stop-loss; capture final theta bleed.",
    },
    "RETAIL_SQUAREOFF": {
        "start": time(15, 0),
        "end": time(15, 30),
        "name": "Last 30 Mins (Retail Intraday Square-Off & Settlement)",
        "primary_actors": "Retail Traders, Broker Auto-Square-Off Algorithms (Zerodha, Groww, AngelOne at 3:15-3:20 PM)",
        "phenomenon": (
            "Forced liquidation of intraday leverage. Retail losers are forcibly closed out, "
            "triggering sharp 10-15 minute short-covering squeezes or sudden market dump."
        ),
        "quant_guidance": "Mandatory hard exit at 3:15 PM for all intraday systems. Never carry intraday losers into closing cross.",
    },
    "MARKET_CLOSED": {
        "start": time(15, 30),
        "end": time(9, 0),
        "name": "Overnight / Off-Hours",
        "primary_actors": "US Markets (NYSE/Nasdaq), GIFT Nifty (GIFT City), Global Central Banks",
        "phenomenon": (
            "Vampire effect overnight compounding occurs while Indian retail sleeps. "
            "GIFT Nifty trades until 2:45 AM IST."
        ),
        "quant_guidance": "Broad index ETF holding is permitted; speculative high-beta intraday holding overnight is prohibited.",
    },
}


def get_current_nse_microstructure_regime(current_time: time | None = None) -> Dict[str, Any]:
    """
    Determine the active NSE market microstructure regime based on IST clock time.
    """
    if current_time is None:
        # Defaults to simulated 9:35 AM IST (Institutional Open) if outside market hours
        now = datetime.now().time()
        current_time = now if time(9, 0) <= now <= time(15, 30) else time(9, 35)

    for regime_key, info in NSE_SESSIONS.items():
        if regime_key == "MARKET_CLOSED":
            continue
        if info["start"] <= current_time < info["end"]:
            return {
                "regime_key": regime_key,
                "current_time_simulated": current_time.strftime("%H:%M:%S"),
                **info,
            }

    closed_info = NSE_SESSIONS["MARKET_CLOSED"]
    return {
        "regime_key": "MARKET_CLOSED",
        "current_time_simulated": current_time.strftime("%H:%M:%S"),
        **closed_info,
    }
