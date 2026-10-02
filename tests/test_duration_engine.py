"""Unit tests for Johansen VECM spread mean-reversion duration engine."""

import math
import numpy as np
import pytest

from nexus_astra.signal_engine.duration_engine import JohansenVECMDurationEngine, DurationMetrics


def test_johansen_vecm_half_life_formula():
    """Verify formula: Duration = ln(0.5) / ln(1 - 1 / theta)."""
    # Theta = 10 -> decay = 0.90 -> ln(0.5)/ln(0.9) = 6.5788
    hl_10 = JohansenVECMDurationEngine.calculate_half_life(10.0)
    expected_10 = math.log(0.5) / math.log(1.0 - 1.0 / 10.0)
    assert pytest.approx(hl_10, rel=1e-4) == expected_10
    assert 6.5 < hl_10 < 6.6

    # Theta = 5 -> decay = 0.80 -> ln(0.5)/ln(0.8) = 3.106
    hl_5 = JohansenVECMDurationEngine.calculate_half_life(5.0)
    assert 3.10 < hl_5 < 3.12

    # Theta = 20 -> decay = 0.95 -> ln(0.5)/ln(0.95) = 13.51
    hl_20 = JohansenVECMDurationEngine.calculate_half_life(20.0)
    assert 13.50 < hl_20 < 13.55


def test_rule_zscore_2_3_garch_low_vol():
    """Rule: Z-Score ~ 2.3 + GARCH low vol = 5-15 days LFT."""
    metrics = JohansenVECMDurationEngine.compute_duration(
        symbol="^NSEI",
        forced_z_score=2.3,
        forced_garch_vol="LOW",
    )
    assert metrics.duration_category == "5-15 days LFT"
    assert 5.0 <= metrics.duration_days <= 15.0
    assert "Z-Score 2.3 + GARCH low vol = 5-15 days LFT" in metrics.regime_rule
    assert metrics.formula == "ln(0.5) / ln(1 - 1/theta)"


def test_rule_zscore_gt_3_garch_high_vol():
    """Rule: Z-Score > 3 + GARCH high = 2-5 days."""
    metrics = JohansenVECMDurationEngine.compute_duration(
        symbol="^NSEI",
        forced_z_score=3.4,
        forced_garch_vol="HIGH",
    )
    assert metrics.duration_category == "2-5 days"
    assert 2.0 <= metrics.duration_days <= 5.0
    assert "Z-Score >3 + GARCH high = 2-5 days" in metrics.regime_rule


def test_rule_cointegration_bank_nifty_pair():
    """Rule: Cointegration Bank Nifty pair = hours to days."""
    metrics = JohansenVECMDurationEngine.compute_duration(
        symbol="BANKNIFTY_PAIR",
        is_bank_nifty_pair=True,
    )
    assert metrics.duration_category == "hours to days"
    assert metrics.duration_days <= 2.5
    assert "Cointegration Bank Nifty pair = hours to days" in metrics.regime_rule


def test_rule_macro_factor():
    """Rule: Macro factor = weeks to months."""
    metrics = JohansenVECMDurationEngine.compute_duration(
        symbol="^NSEI",
        dominant_factor="MACRO",
    )
    assert metrics.duration_category == "weeks to months"
    assert metrics.duration_days >= 20.0
    assert "Macro factor = weeks to months" in metrics.regime_rule


def test_vecm_theta_estimation_synthetic_mean_reversion():
    """Test theta estimation on stationary Ornstein-Uhlenbeck series."""
    np.random.seed(42)
    n = 100
    prices = np.zeros(n)
    prices[0] = 100.0
    alpha_true = -0.15  # theta_true = 1/0.15 = 6.67
    for i in range(1, n):
        prices[i] = prices[i-1] + alpha_true * (prices[i-1] - 100.0) + np.random.normal(0, 0.5)

    theta, z = JohansenVECMDurationEngine.estimate_vecm_theta(prices)
    assert theta > 1.0
    half_life = JohansenVECMDurationEngine.calculate_half_life(theta)
    assert half_life > 0.0
