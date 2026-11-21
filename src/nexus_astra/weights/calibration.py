"""Walk-forward probability calibration for dataset-level scores."""

from __future__ import annotations

import logging
from typing import Iterable, Sequence

import numpy as np

logger = logging.getLogger(__name__)


class ProbabilityCalibrator:
    def __init__(self, folds: int = 5) -> None:
        self.folds = folds
        self.platt_a = 1.0
        self.platt_b = 0.0
        self.isotonic = None

    @staticmethod
    def platt_probability(score: float | np.ndarray, a: float = 1.0, b: float = 0.0) -> float | np.ndarray:
        z = a * np.asarray(score, dtype=float) + b
        z = np.clip(z, -40.0, 40.0)
        prob = 1.0 / (1.0 + np.exp(-z))
        return float(prob) if np.asarray(score).ndim == 0 else prob

    def fit_cpcv(self, scores: Sequence[float], outcomes: Sequence[int]) -> "ProbabilityCalibrator":
        """Purged walk-forward CPCV: 5 chronologically expanding training folds."""
        x = np.asarray(scores, dtype=float).reshape(-1)
        y = np.asarray(outcomes, dtype=float).reshape(-1)
        if len(x) != len(y) or len(x) == 0:
            return self

        oof = np.full(len(x), np.nan)
        cut = max(2, len(x) // (self.folds + 1))
        try:
            from sklearn.linear_model import LogisticRegression
            for fold in range(1, self.folds + 1):
                train_end = min(len(x) - 1, cut * fold)
                test_start = train_end
                test_end = min(len(x), test_start + max(1, (len(x) - cut) // self.folds))
                if test_start >= len(x):
                    break
                tr_x, tr_y = x[:train_end].reshape(-1, 1), y[:train_end]
                te_x = x[test_start:test_end].reshape(-1, 1)
                if len(np.unique(tr_y)) < 2:
                    continue
                model = LogisticRegression().fit(tr_x, tr_y)
                oof[test_start:test_end] = model.predict_proba(te_x)[:, 1]

            valid = ~np.isnan(oof)
            if np.sum(valid) >= 2:
                full_model = LogisticRegression().fit(x.reshape(-1, 1), y)
                self.platt_a = float(full_model.coef_[0, 0])
                self.platt_b = float(full_model.intercept_[0])
                try:
                    from sklearn.isotonic import IsotonicRegression
                    iso = IsotonicRegression(out_of_bounds="clip")
                    iso.fit(oof[valid], y[valid])
                    self.isotonic = iso
                except Exception:
                    self.isotonic = None
        except Exception as exc:
            logger.warning("Calibration unavailable: %s", exc)
        return self

    def calibrate(self, score: float) -> float:
        prob = self.platt_probability(score, self.platt_a, self.platt_b)
        if self.isotonic is not None:
            iso_prob = float(self.isotonic.predict([prob])[0])
            prob = 0.5 * prob + 0.5 * iso_prob
        return min(1.0, max(0.0, float(prob)))


def brier_score(y_true: Sequence[int], probabilities: Sequence[float]) -> float:
    y = np.asarray(y_true, dtype=float)
    p = np.asarray(probabilities, dtype=float)
    if len(y) == 0:
        return 0.0
    return float(np.mean((p - y) ** 2))


def log_loss(y_true: Sequence[int], probabilities: Sequence[float]) -> float:
    y = np.asarray(y_true, dtype=float)
    p = np.clip(np.asarray(probabilities, dtype=float), 1e-12, 1 - 1e-12)
    if len(y) == 0:
        return 0.0
    return float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)))


def deflated_sharpe(sharpe: float, trials: int = 1, n_obs: int = 252) -> float:
    """Simplified deflated Sharpe probability approximation."""
    if n_obs < 2:
        return 0.0
    z = sharpe * np.sqrt(max(n_obs - 1, 1) / 2.0)
    try:
        from scipy.stats import norm
        return float(norm.cdf(z - np.log(max(trials, 1)) / np.sqrt(n_obs)))
    except Exception:
        return float(max(0.0, min(1.0, 0.5 + 0.5 * z / np.sqrt(1 + z * z))))


def combine_dataset_probabilities(weights: dict[str, float], probabilities: dict[str, float]) -> float:
    total = sum(weights.values())
    if total <= 0:
        return 0.5
    return float(min(1.0, max(0.0, sum(weights.get(k, 0.0) * float(p) for k, p in probabilities.items()) / total)))
