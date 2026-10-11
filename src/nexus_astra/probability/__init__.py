"""Advanced Probability & Statistical Edge Engine.

Components:
- Kelly Criterion & Half-Kelly Sizing (Full Kelly 25%, Half Kelly 12.5% cap)
- Bayesian Base Rate Updating (8% prior doubling base rate, avoids base rate neglect)
- Expected Value (EV) Calculator (Net EV after Indian STT/brokerage friction; skips EV <= 0)
- Second-Order Statistics (Lag-1 autocorrelation > 0.3, positive P&L skewness, MAE stop-loss calibration)
"""

from __future__ import annotations

from nexus_astra.probability.kelly import calculate_institutional_kelly
from nexus_astra.probability.bayes_base_rate import compute_bayesian_posterior
from nexus_astra.probability.ev_calculator import calculate_trade_expected_value
from nexus_astra.probability.second_order_stats import compute_second_order_statistics

__all__ = [
    "calculate_institutional_kelly",
    "compute_bayesian_posterior",
    "calculate_trade_expected_value",
    "compute_second_order_statistics",
]
