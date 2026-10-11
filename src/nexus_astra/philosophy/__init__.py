"""Top 2% Quant Trading Philosophy & Risk Architecture.

Components:
1. Ergodicity Economics (Ensemble != Time average, drawdown recovery asymmetry, survival > return)
2. Soros Reflexivity (High valuations -> massive primary IPO paper supply -> secondary liquidity drain)
3. Antifragile 80/20 Barbell (80% sovereign safe floor / Liquid Bees + 20% convex asymmetric right-tail options)
4. The Loser's Game (Winning by avoiding unforced errors, stand down on 60% of ambiguous trading sessions)
"""

from __future__ import annotations

from nexus_astra.philosophy.ergodicity import compute_ergodicity_recovery_burden
from nexus_astra.philosophy.reflexivity import evaluate_soros_reflexivity_drag
from nexus_astra.philosophy.antifragile import compute_antifragile_barbell_allocation
from nexus_astra.philosophy.losers_game import evaluate_unforced_error_risk

__all__ = [
    "compute_ergodicity_recovery_burden",
    "evaluate_soros_reflexivity_drag",
    "compute_antifragile_barbell_allocation",
    "evaluate_unforced_error_risk",
]
