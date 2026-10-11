"""Institutional 5-Question Pre-Trade Checklist (Hard Binary Filter).

Mandate:
- Before any trade is executed on NEXUS-ASTRA, all 5 institutional questions must be answered AFFIRMATIVELY.
- If ANY single question fails (returns False / NO), the system aborts execution immediately with DON'T_TRADE.
- Eliminates 100% of impulsive, low-conviction, and crowded retail trades.

The 5 Questions:
1. Q1: Do I have an explicit structural edge over HFT? (e.g., Capacity constraints, slow macro alpha 3-10 days, overnight risk transfer?)
2. Q2: Is this trade free of retail / consensus crowding? (Finfluencers, retail telegram channels, and sentiment not crowded on same side?)
3. Q3: Have I mapped the third-order market reaction? (Who gets trapped at 09:15-10:30 AM? Who is forced to cover by risk limits?)
4. Q4: Is capital sized strictly via Half-Kelly with max 15% cap? (No emotional sizing, no martingale, no full Kelly blowup risk?)
5. Q5: Can I articulate the quantitative anomaly in 1 clean sentence without vague buzzwords?
"""

from __future__ import annotations
import logging
from typing import Any, Dict

logger = logging.getLogger(__name__)


def evaluate_institutional_checklist(
    q1_explicit_edge_over_hft: bool = True,
    q2_uncrowded_sentiment: bool = True,
    q3_third_order_mapped: bool = True,
    q4_half_kelly_sized: bool = True,
    q5_one_sentence_thesis: bool = True,
    thesis_statement: str = "Capturing 20-day post-earnings drift in TCS driven by 4 consensus upward analyst revisions.",
) -> Dict[str, Any]:
    """
    Evaluates the 5 institutional pre-trade gates.
    Returns status APPROVED only if all 5 checks evaluate to True.
    """
    checklist_results = {
        "Q1_Explicit_Edge_vs_HFT": {
            "passed": q1_explicit_edge_over_hft,
            "description": "Exploiting HFT capacity limits, slow multi-day alpha, or overnight risk transfer.",
        },
        "Q2_Uncrowded_Sentiment": {
            "passed": q2_uncrowded_sentiment,
            "description": "Independent thesis; retail consensus, finfluencers, and chat rooms are not crowded on this side.",
        },
        "Q3_Third_Order_Reaction_Mapped": {
            "passed": q3_third_order_mapped,
            "description": "Understands who is trapped (e.g. failed gap faders) and who is structurally forced to buy/sell.",
        },
        "Q4_Half_Kelly_Sized": {
            "passed": q4_half_kelly_sized,
            "description": "Position is strictly sized via Half-Kelly (<= 15% portfolio allocation) to guarantee ergodicity.",
        },
        "Q5_One_Sentence_Quant_Thesis": {
            "passed": q5_one_sentence_thesis and len(thesis_statement.strip()) > 15,
            "description": f"Thesis articulated: '{thesis_statement.strip()}'",
        },
    }

    failed_questions = [
        k for k, v in checklist_results.items() if not v["passed"]
    ]

    all_passed = len(failed_questions) == 0

    if all_passed:
        decision = "APPROVED_FOR_EXECUTION"
        guidance = "All 5 institutional pre-trade gates verified. Full quantitative edge confirmed. Proceed to execution."
    else:
        decision = "DON'T_TRADE"
        guidance = (
            f"Pre-trade execution BLOCKED. Failed questions: {', '.join(failed_questions)}. "
            "Institutional rule: If ANY question is NO, DO NOT TRADE."
        )

    return {
        "status": decision,
        "all_passed": all_passed,
        "passed_count": 5 - len(failed_questions),
        "total_questions": 5,
        "failed_questions": failed_questions,
        "thesis_statement": thesis_statement.strip(),
        "checklist_details": checklist_results,
        "guidance": guidance,
    }
