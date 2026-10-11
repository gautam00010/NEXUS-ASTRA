"""Unit tests for Overnight Drift / Vampire Effect anomaly module."""

import pytest
import numpy as np
import pandas as pd

from nexus_astra.anomalies import (
    decompose_returns,
    calculate_compounding_asymmetry,
    calculate_time_weighted_exposure,
    generate_micron_sawtooth_data,
    knuteson_test,
    INNOCUOUS_THEORY,
    KNUTESON_ACCUSATION,
    ACADEMIC_LITERATURE,
    HARSH_REALITY,
    get_anomaly_theories_summary,
    ANOMALY_PAPERS,
    get_papers_bibliography,
)
from nexus_astra.anomalies.overnight_drift import EMPIRICAL_ANOMALY_BENCHMARKS
from nexus_astra.signal_engine.vectorbt_engine import (
    run_overnight_backtest,
    overnight_drift_filter,
)
from nexus_astra.portfolio.riskfolio_engine import apply_overnight_drift_overlay


def test_decompose_returns_identity():
    """Verify that (1 + total) == (1 + overnight) * (1 + intraday) identity holds."""
    dates = pd.date_range("2026-01-01", periods=10, freq="B")
    # Synthetic prices
    opens = [100.0, 102.0, 101.0, 104.0, 103.0, 105.0, 106.0, 105.5, 108.0, 107.0]
    closes = [101.5, 101.0, 103.5, 103.0, 104.5, 105.8, 105.0, 107.5, 106.5, 109.0]
    df = pd.DataFrame({"Open": opens, "Close": closes}, index=dates)

    res = decompose_returns(df)
    assert "overnight_ret" in res.columns
    assert "intraday_ret" in res.columns
    assert "total_ret" in res.columns
    assert "overnight_cum" in res.columns

    # Test identity for row t=1 (second row)
    o_ret = res["overnight_ret"].iloc[1]
    i_ret = res["intraday_ret"].iloc[1]
    t_ret = res["total_ret"].iloc[1]

    expected_total = (1.0 + o_ret) * (1.0 + i_ret) - 1.0
    assert t_ret == pytest.approx(expected_total, rel=1e-6)


def test_calculate_compounding_asymmetry():
    """Verify exponential asymmetry and variance drag calculations."""
    res = calculate_compounding_asymmetry(daily_edge=0.0015, days=9200)
    assert res["daily_edge_pct"] == pytest.approx(0.15, abs=0.01)
    assert res["overnight_multiplier"] > 500000.0
    assert res["intraday_multiplier"] < 0.01
    assert res["variance_drag_example_pct"] == pytest.approx(-4.0, abs=0.01)
    assert "Compounding asymmetry" in res["insight"]


def test_calculate_time_weighted_exposure():
    """Verify weekly market open (19.34%) vs closed (80.66%) distribution."""
    res = calculate_time_weighted_exposure()
    assert res["open_hours_per_week"] == 32.5
    assert res["closed_hours_per_week"] == 135.5
    assert res["open_pct"] == pytest.approx(19.35, abs=0.1)
    assert res["closed_pct"] == pytest.approx(80.65, abs=0.1)
    assert res["ratio_closed_to_open"] == pytest.approx(4.17, abs=0.1)


def test_generate_micron_sawtooth_data():
    """Verify replication of Micron 1990-2026 sawtooth path."""
    df = generate_micron_sawtooth_data(num_points=100)
    assert len(df) == 100
    assert "Overnight_Cum" in df.columns
    assert "Intraday_Cum" in df.columns
    assert "Buy_Hold_Cum" in df.columns
    # Final overnight should be huge (~1.38M multiplier)
    assert df["Overnight_Cum"].iloc[-1] > 100000.0
    # Final intraday should be near 0 (< 0.002)
    assert df["Intraday_Cum"].iloc[-1] < 0.005
    # Final buy and hold should be ~1100x
    assert df["Buy_Hold_Cum"].iloc[-1] == pytest.approx(1100.0, rel=1e-2)


def test_knuteson_test_benchmarks():
    """Verify knuteson_test returns empirical anomaly benchmarks."""
    results = knuteson_test(universe=["RELIANCE.NS", "MU", "CHINA_CSI300"])
    assert "RELIANCE.NS" in results
    assert "MU" in results
    assert "CHINA_CSI300" in results

    rel = results["RELIANCE.NS"]
    assert rel["overnight_cum_pct"] >= 1000.0
    assert rel["drift_ratio"] > 10.0

    china = results["CHINA_CSI300"]
    assert china["drift_ratio"] < 0.0  # Negative overnight exception


def test_vectorbt_run_overnight_backtest():
    """Verify run_overnight_backtest demonstrates friction edge destruction."""
    res = run_overnight_backtest(fees=0.001, slippage=0.0005)
    assert "overnight_gross_pct" in res
    assert "overnight_net_pct" in res
    assert "friction_drag_pct" in res
    assert "friction_kills_edge" in res
    # Transaction costs must cause significant drag
    assert res["friction_drag_pct"] > 20.0
    assert res["round_trip_cost_bps"] == 30.0


def test_vectorbt_overnight_drift_filter():
    """Verify overnight_drift_filter produces actionable risk guidance."""
    # High drift case
    filter_res = overnight_drift_filter(threshold=1.5)
    assert filter_res["action"] == "AVOID_INTRADAY_HOLD_OVERNIGHT"
    assert filter_res["intraday_allowed"] is False
    assert 10.0 <= filter_res["recommended_overlay_pct"] <= 20.0
    assert 5.0 <= filter_res["gap_risk_stop_pct"] <= 10.0

    # Negative drift exception (like China)
    neg_series = pd.Series([-0.5] * 20)
    filter_neg = overnight_drift_filter(data=neg_series, threshold=1.5)
    assert filter_neg["action"] == "FAVOR_INTRADAY_EXCEPTION"
    assert filter_neg["intraday_allowed"] is True


def test_riskfolio_apply_overnight_drift_overlay():
    """Verify overnight drift overlay tilts toward positive drift and penalizes negative drift."""
    base_weights = {"RELIANCE": 0.40, "TCS": 0.35, "CHINA": 0.25}
    drift_ratios = {"RELIANCE": 21.4, "TCS": 26.8, "CHINA": -0.24}

    res = apply_overnight_drift_overlay(base_weights, drift_ratios, max_overlay=0.20, gap_risk_stop=0.07)
    assert "overlay_weights" in res
    adj_weights = res["overlay_weights"]

    # Sum of adjusted weights should remain 1.0
    assert sum(adj_weights.values()) == pytest.approx(1.0, abs=1e-3)
    # CHINA (negative drift) must be tilted downward
    assert adj_weights["CHINA"] < base_weights["CHINA"]
    # Positive drift assets must gain weight or maintain dominant allocation
    assert adj_weights["TCS"] > base_weights["TCS"]
    assert res["overlay_applied_pct"] == 20.0
    assert res["gap_risk_stop_pct"] == 7.0


def test_theories_and_papers_modules():
    """Verify theories, unproven allegations disclaimers, and academic papers."""
    theories = get_anomaly_theories_summary()
    assert "innocuous" in theories
    assert "knuteson" in theories
    assert "academic" in theories
    assert "harsh_reality" in theories

    # Verify disclaimer is explicitly present
    knut = theories["knuteson"]
    assert "UNPROVEN_ALLEGATION" in knut["status"]
    assert "DISCLAIMER" in knut["disclaimer"]

    papers = get_papers_bibliography()
    assert len(papers) >= 4
    cits = [p["citation"] for p in papers]
    assert any("2010.01727" in c for c in cits)
    assert any("Haghani" in p["authors"] for p in papers)
