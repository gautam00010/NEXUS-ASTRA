"""Bayesian Base Rate Engine (Preventing Base Rate Neglect).

Mechanism:
- Base Rate Neglect is the #1 cognitive error of retail traders.
- Example:
  * Prior Base Rate P(Double): In the Indian equity universe, the annual probability of any stock doubling is only ~8.0% (0.08).
  * Indicator Reliability: A breakout indicator has a 70% True Positive Rate P(Signal | Double) = 0.70,
    and a 20% False Positive Rate P(Signal | NotDouble) = 0.20.
  * When the indicator fires, retail assumes a 70% probability of success.
  * Bayesian Reality:
      P(Signal) = (0.70 * 0.08) + (0.20 * 0.92) = 0.056 + 0.184 = 0.240
      P(Double | Signal) = (0.70 * 0.08) / 0.240 = 23.33%
  * The actual chance of a doubling run is only 23.3%, NOT 70%!
- Institutional quants anchor expectations on the base rate before allocating capital.
"""

from __future__ import annotations
import logging
from typing import Any, Dict

logger = logging.getLogger(__name__)


def compute_bayesian_posterior(
    prior_base_rate: float = 0.08,             # 8.0% empirical base rate of 1-year doubling / massive multi-bagger
    true_positive_rate: float = 0.70,          # Sensitivity: P(Signal | True Setup)
    false_positive_rate: float = 0.20,         # False alarm rate: P(Signal | Noise)
) -> Dict[str, Any]:
    """
    Computes true Bayesian posterior probability given an observed signal.
    """
    if not (0.0 < prior_base_rate < 1.0):
        raise ValueError("prior_base_rate must be between 0 and 1 exclusive")
    if not (0.0 < true_positive_rate <= 1.0):
        raise ValueError("true_positive_rate must be in (0, 1]")
    if not (0.0 <= false_positive_rate < 1.0):
        raise ValueError("false_positive_rate must be in [0, 1)")

    p_h = prior_base_rate
    p_not_h = 1.0 - p_h

    # Total probability of signal firing
    p_signal = (true_positive_rate * p_h) + (false_positive_rate * p_not_h)

    # Posterior probability via Bayes' Theorem
    posterior = (true_positive_rate * p_h) / max(p_signal, 1e-9)

    # Information Gain (Bayes Factor)
    bayes_factor = true_positive_rate / max(false_positive_rate, 1e-9)

    return {
        "prior_base_rate_pct": round(prior_base_rate * 100.0, 2),
        "signal_true_positive_rate_pct": round(true_positive_rate * 100.0, 2),
        "signal_false_positive_rate_pct": round(false_positive_rate * 100.0, 2),
        "total_signal_probability_pct": round(p_signal * 100.0, 2),
        "true_posterior_probability_pct": round(posterior * 100.0, 2),
        "bayes_factor": round(bayes_factor, 2),
        "retail_perception_bias": round(true_positive_rate * 100.0 - posterior * 100.0, 2),
        "verdict": (
            f"Prior base rate is {prior_base_rate * 100:.1f}%. While the signal has {true_positive_rate * 100:.1f}% accuracy, "
            f"false alarms dilute true probability to {posterior * 100:.1f}%. Adjust position sizing downward accordingly."
        ),
    }
