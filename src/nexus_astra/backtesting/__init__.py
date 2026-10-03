"""Backtesting and Paper Trading modules for NEXUS-ASTRA."""

from .cost_model import CostBreakdown, IndiaCostModel, cost_model
from .paper_trader import PaperTrader
from .survivorship_bias import SurvivorshipCorrector
from .vectorbt_engine import VectorBTEngine, generate_signals
WalkForwardBacktester = VectorBTEngine

__all__ = [
    "CostBreakdown",
    "IndiaCostModel",
    "cost_model",
    "PaperTrader",
    "SurvivorshipCorrector",
    "VectorBTEngine",
    "WalkForwardBacktester",
    "generate_signals",
]
