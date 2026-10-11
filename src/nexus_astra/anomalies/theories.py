"""Theoretical explanations for the Overnight Drift / Vampire Effect anomaly.

Covers:
1. Innocuous Explanations (News timing, Retail vs Inst flow, Overnight Risk Premium).
2. Knuteson Manipulation Accusation (arXiv:2010.01727 - explicitly framed as unproven allegation).
3. Academic Literature & Empirical Consensus (Haghani & White 2022, Lou et al. 2019).
4. Harsh Reality (Transaction friction, execution barrier, catastrophic gap risk).
"""

from __future__ import annotations
from typing import Any, Dict

INNOCUOUS_THEORY: Dict[str, Any] = {
    "title": "Innocuous Market Microstructure & Structural Flow Theories",
    "status": "MAINSTREAM_ACCEPTED",
    "drivers": [
        {
            "name": "Asymmetric Information & News Timing",
            "mechanism": (
                "Over 85% of corporate quarterly earnings releases, FDA decisions, major M&A announcements, "
                "and Federal Reserve policy shifts occur either post-market (after 4:00 PM EST / 3:30 PM IST) "
                "or pre-market (before 9:30 AM EST / 9:15 AM IST). Consequently, true fundamental revaluations "
                "occur almost entirely between market sessions while order books are thin, creating overnight gap jumps."
            ),
        },
        {
            "name": "Retail vs. Institutional Order Flow Asymmetry",
            "mechanism": (
                "Retail investors disproportionately enter market-on-open (MOO) buy orders based on overnight news "
                "and social media sentiment, pushing opening prices up. Conversely, institutional asset managers "
                "and algorithmic execution desks systematically sell or distribute inventory throughout the intraday session "
                "using TWAP/VWAP algorithms, creating persistent downward drift from open to close."
            ),
        },
        {
            "name": "Overnight Risk Compensation Premium",
            "mechanism": (
                "Investors cannot dynamically manage risk or execute stop-losses when exchanges are closed. "
                "Holding inventory overnight exposes capital to illiquid jump risk and geopolitical shocks. "
                "In classical asset pricing theory, bearing unhedgeable non-continuous risk demands a positive expected return premium."
            ),
        },
    ],
}

KNUTESON_ACCUSATION: Dict[str, Any] = {
    "title": "Knuteson Systematic Algorithmic Manipulation Accusation (arXiv:2010.01727)",
    "status": "UNPROVEN_ALLEGATION_DISCLAIMER",
    "author": "Bruce Knuteson (Former MIT Physicist & D.E. Shaw Quantitative Researcher)",
    "disclaimer": (
        "IMPORTANT DISCLAIMER & LEGAL NOTICE: The following hypothesis represents an unproven allegation "
        "published in pre-print form by Dr. Bruce Knuteson. It has NOT been substantiated by the SEC, CFTC, "
        "or academic peer-reviewed consensus, and is vigorously contested by institutional market participants "
        "and financial journalists (e.g., Robin Wigglesworth in the Financial Times). "
        "It is included here strictly for comprehensive quantitative historiography and academic research."
    ),
    "core_thesis": (
        "Knuteson argues that large quantitative hedge funds systematically expand prices overnight and into the open "
        "by executing aggressive buy orders during illiquid off-hours auctions. Because liquidity is thin, small buying "
        "drives substantial upward price impact. During regular trading hours when liquidity is 10x higher, the firms "
        "slowly unwind the inventory with minimal downward impact. Compounded over decades across 21 global indices, "
        "this creates the artificial appearance of massive overnight gains (+1000% to +138M%) paired with persistent daytime decay (-60% to -99%)."
    ),
    "global_footprint": {
        "indices_observed": 21,
        "consistent_patterns": ["US (SPY, QQQ, MU)", "India (NIFTY 50)", "Germany (DAX)", "Canada (TSX)", "Japan (Nikkei)"],
        "notable_counterexample": "China (CSI 300 / SSE) - exhibits negative overnight drift due to T+1 settlement rules and retail-dominated intraday speculative flow.",
    },
}

ACADEMIC_LITERATURE: Dict[str, Any] = {
    "title": "Empirical Academic Literature & Peer-Reviewed Research",
    "status": "PEER_REVIEWED_CONSENSUS",
    "key_findings": [
        {
            "study": "Haghani & White (2022) - 'Night Moves: Is the Overnight Drift Anomaly Real?' (Elm Partners)",
            "finding": (
                "Showed that $1 invested in SPY from 1992 to 2020 yielded $17.50 overnight versus only $0.87 intraday. "
                "Found that the effect is dramatically amplified in high-attention, retail-heavy equities "
                "(such as NVDA, TSLA, AMD, and MSTR), where overnight price discovery dominates."
            ),
        },
        {
            "study": "Lou, Polk, and Skouras (2019) - 'A Tug of War: Overnight Versus Intraday Expected Returns' (Journal of Financial Economics)",
            "finding": (
                "Documented that equity momentum profits are earned entirely overnight and reverse intraday. "
                "Attributed the daytime reversal to institutional mutual fund rebalancing and institutional liquidity provision."
            ),
        },
        {
            "study": "Lachance (2015) - 'Night Trading: Lower Risk but Higher Return?'",
            "finding": (
                "Demonstrated that overnight return variances are significantly lower than intraday variances, "
                "yet overnight returns capture virtually all cumulative equity market premiums across multiple decades."
            ),
        },
    ],
}

HARSH_REALITY: Dict[str, Any] = {
    "title": "Harsh Realities of Implementation: Why Retail Cannot Arbitrage Overnight Drift",
    "status": "CRITICAL_EXECUTION_WARNING",
    "friction_barriers": [
        {
            "barrier": "Frictional Annihilation (Transaction Costs & Fees)",
            "impact": (
                "A naive strategy of buying at 3:59 PM and selling at 9:30 AM requires 252 round-trip transactions per year. "
                "Even with zero commission, typical retail exchange turnover fees, clearing charges, and SEC/STT taxes "
                "(e.g., Indian STT 0.1% + GST) impose a drag of at least 15-30% annually, instantly destroying the modest "
                "0.05% - 0.15% average overnight edge."
            ),
        },
        {
            "barrier": "Pre-Market / Post-Market Auction Illiquidity",
            "impact": (
                "Exchanges do not guarantee fill at the exact print close or open. Executing during closing and opening "
                "crosses exposes market orders to severe bid-ask spread widening (often 10-30 bps) and adverse selection from HFTs."
            ),
        },
        {
            "barrier": "Unhedgeable Overnight Gap Risk & Black Swan Discontinuities",
            "impact": (
                "Overnight positions carry jump risk without stop-loss protection. Earnings misses, unexpected geopolitical conflicts, "
                "or macroeconomic announcements can gap the underlying stock down 10% to 25% at open, inducing irreversible drawdown."
            ),
        },
    ],
    "actionable_guidance": (
        "NEVER attempt high-frequency overnight/intraday flipping on individual equities. "
        "Instead, utilize the drift phenomenon as an ALLOCATION OVERLAY (10-20% portfolio tilt in broad index ETFs) "
        "and an INTRADAY AVOIDANCE FILTER: avoid day-trading high-beta equities that suffer from structural intraday decay."
    ),
}


def get_anomaly_theories_summary() -> Dict[str, Any]:
    """Retrieve structured summary of all overnight drift theories and reality checks."""
    return {
        "innocuous": INNOCUOUS_THEORY,
        "knuteson": KNUTESON_ACCUSATION,
        "academic": ACADEMIC_LITERATURE,
        "harsh_reality": HARSH_REALITY,
    }
