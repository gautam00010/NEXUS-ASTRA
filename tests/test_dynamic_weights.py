from __future__ import annotations

import numpy as np

from nexus_astra.weights.dynamic_weights import DynamicWeightEngine
from nexus_astra.weights.calibration import ProbabilityCalibrator, brier_score
from nexus_astra.signal_engine.gates import Gates


def test_weights_sum_to_one_all_regimes():
    engine = DynamicWeightEngine()
    for regime in ("TRENDING", "MEAN_REVERTING", "HIGH_VOL_SHOCK", "MACRO_RISK_OFF"):
        weights = engine.calculate_weights(regime)
        assert abs(sum(weights.values()) - 1.0) < 1e-9


def test_trending_boosts_momentum():
    engine = DynamicWeightEngine()
    flat = engine.calculate_weights("MEAN_REVERTING")
    trending = engine.calculate_weights("TRENDING")
    assert trending["momentum"] > flat["momentum"]


def test_mean_reverting_boosts_mean_reversion():
    engine = DynamicWeightEngine()
    weights = engine.calculate_weights("MEAN_REVERTING")
    assert weights["mean_reversion"] == max(weights.values())


def test_negative_sharpe_floor():
    engine = DynamicWeightEngine()
    weights = engine.calculate_weights(
        "TRENDING",
        performance={"momentum": {"sharpe": -2.0}},
    )
    assert weights["momentum"] >= 0.05


def test_contextual_thesis_weights():
    engine = DynamicWeightEngine()
    fii = engine.calculate_weights("TRENDING", thesis="200-EMA support + FII accumulation")
    zscore = engine.calculate_weights("MEAN_REVERTING", thesis="Z-Score 2.3 + GARCH Low Vol mean-reversion")
    filing = engine.calculate_weights("TRENDING", thesis="EDGAR 20-F filing clean")
    assert fii["fii_dii"] > engine.calculate_weights("TRENDING")["fii_dii"]
    assert zscore["mean_reversion"] > engine.calculate_weights("MEAN_REVERTING")["mean_reversion"]
    assert filing["fundamentals_edgar"] > engine.calculate_weights("TRENDING")["fundamentals_edgar"]


def test_soft_gate_never_no_trade():
    penalties = Gates.run_all_gates(
        last_update=__import__("datetime").datetime.now(__import__("datetime").timezone.utc),
        symbol="TCS",
        adv_cr=0.0,
        vix=30.0,
        fii_5d_cum_cr=-20000,
        price=4210,
        ema_200=4200,
        fii_trend_bullish=False,
        trade_long=True,
        setup="invalid",
    )
    assert penalties["status"] == "PASS"
    assert "NO_TRADE" not in penalties


def test_calibration_brier_below_threshold():
    rng = np.random.default_rng(42)
    scores = np.linspace(-2, 2, 200)
    outcomes = (scores + rng.normal(0, 0.4, len(scores)) > 0).astype(int)
    calibrator = ProbabilityCalibrator().fit_cpcv(scores.tolist(), outcomes.tolist())
    probabilities = [calibrator.calibrate(float(x)) for x in scores]
    assert brier_score(outcomes.tolist(), probabilities) < 0.20
