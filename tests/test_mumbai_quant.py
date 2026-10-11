"""Unit tests for Mumbai BSE/NSE + Crypto practical quant concepts and strategies."""

import pytest
import numpy as np
import pandas as pd

from nexus_astra.theories import (
    decompose_nse,
    analyze_symbol_drift,
    calculate_sharpe_ratio,
    calculate_sortino_ratio,
    rank_strategies_risk_adjusted,
    get_current_nse_microstructure_regime,
    calculate_expectancy,
    simulate_equity_curve,
)
from nexus_astra.strategies import (
    generate_orb_signal,
    backtest_orb_vectorbt,
    calculate_vwap_bands,
    generate_vwap_reversion_signal,
    evaluate_gap_fade_follow,
    select_momentum_lowvol_basket,
    calculate_pair_spread,
    generate_pairs_trading_signal,
    fetch_binance_funding_rate,
    evaluate_crypto_funding_edge,
    generate_0dte_strangle_strikes,
    simulate_0dte_decay,
)
from nexus_astra.risk.bias_alerts import (
    check_disposition_effect,
    check_overnight_risk_bias,
    check_recency_bias,
    check_lottery_bias,
    check_anchoring_bias,
    evaluate_trader_biases,
)
from nexus_astra.toolkit.metrics import (
    atr_position_sizing,
    rsi_volume_confirmation,
    correlation_cluster_check,
    backtest_quality_filter,
)
from nexus_astra.starter.paper_system import MumbaiStarterPaperSystem


# ==============================================================================
# 1. CORE THEORIES TESTS
# ==============================================================================
def test_decompose_nse_identity():
    """Verify return decomposition identity on NSE synthetic candles."""
    df = pd.DataFrame({
        "Open": [100.0, 103.0, 102.0],
        "Close": [102.0, 101.5, 104.0],
    })
    res = decompose_nse(df)
    o_ret = res["overnight_ret"].iloc[1]
    i_ret = res["intraday_ret"].iloc[1]
    t_ret = res["total_ret"].iloc[1]
    expected = (1.0 + o_ret) * (1.0 + i_ret) - 1.0
    assert t_ret == pytest.approx(expected, rel=1e-5)


def test_analyze_symbol_drift_reliance():
    """Verify empirical Reliance and TCS overnight dominance benchmarks."""
    from nexus_astra.theories.return_decomposition import get_nse_overnight_benchmarks
    benchmarks = get_nse_overnight_benchmarks()
    assert benchmarks["RELIANCE.NS"]["overnight_cum_pct"] == 1868.0
    assert benchmarks["RELIANCE.NS"]["drift_ratio"] == 21.4

    drift_res = analyze_symbol_drift("RELIANCE.NS")
    assert drift_res["overnight_cum_pct"] > 0.0
    assert drift_res["drift_ratio"] > 1.0


def test_sharpe_vs_sortino_downside_ranking():
    """Verify Sortino penalizes downside only and ranks 15%/10% strategy higher than 30%/40%."""
    # Strategy A: 30% return, 40% vol
    # Strategy B: 15% return, 10% vol
    ranked = rank_strategies_risk_adjusted([
        {"name": "Gambler", "annual_return_pct": 30.0, "annual_vol_pct": 40.0, "annual_downside_vol_pct": 32.0, "rf_pct": 6.5},
        {"name": "Compounder", "annual_return_pct": 15.0, "annual_vol_pct": 10.0, "annual_downside_vol_pct": 5.0, "rf_pct": 6.5},
    ])
    # Compounder must rank #1
    assert ranked[0]["name"] == "Compounder"
    assert ranked[0]["sharpe_ratio"] > ranked[1]["sharpe_ratio"]
    assert ranked[0]["sortino_ratio"] > 1.5


def test_nse_microstructure_regime_clock():
    """Verify microstructure session regimes on NSE."""
    regime = get_current_nse_microstructure_regime()
    assert "regime_key" in regime
    assert "name" in regime
    assert "primary_actors" in regime


def test_probability_edge_expectancy():
    """Verify 51% win rate with 1:2 R:R gives +0.53R positive expectancy."""
    exp_res = calculate_expectancy(win_rate=0.51, avg_win_r=2.0, avg_loss_r=1.0)
    assert exp_res["expectancy_r_per_trade"] == pytest.approx(0.53, abs=0.01)
    assert exp_res["is_positive_edge"] is True


# ==============================================================================
# 2. 7 PRACTICAL STRATEGIES TESTS
# ==============================================================================
def test_orb_strategy_and_backtest():
    """Verify ORB breakout trigger and VectorBT C++ backtest."""
    sig = generate_orb_signal(current_price=22150.0, current_volume=200000.0)
    assert sig["signal"] == "BUY_BREAKOUT"
    assert sig["target_2r"] > sig["current_price"]

    bt = backtest_orb_vectorbt(days=60)
    assert bt["engine"] == "VectorBT C++ Numba"
    assert "sharpe_ratio" in bt


def test_vwap_reversion_strategy():
    """Verify VWAP 2-sigma reversion on BankNifty and rejection on low liquidity."""
    sig_bank = generate_vwap_reversion_signal(current_price=48600.0, vwap=48200.0, vwap_std=150.0, symbol="BANKNIFTY")
    assert sig_bank["signal"] == "SHORT_REVERSION"

    sig_small = generate_vwap_reversion_signal(current_price=55.0, vwap=50.0, vwap_std=2.0, symbol="PENNY_SME")
    assert sig_small["signal"] == "BLOCKED_LOW_LIQUIDITY"


def test_gap_fade_vs_follow():
    """Verify 68% fade rate on news-less gap vs follow on RBI macro catalyst."""
    # No news -> FADE
    fade = evaluate_gap_fade_follow(prev_close=22000.0, open_price=22250.0, news_headlines=["NORMAL_DAY"])
    assert fade["decision"] == "GAP_FADE_MEAN_REVERSION"
    assert fade["fade_probability_pct"] == 68.0

    # News catalyst -> FOLLOW
    follow = evaluate_gap_fade_follow(prev_close=22000.0, open_price=22250.0, news_headlines=["RBI CUTS REPO RATE BY 25 BPS"])
    assert follow["decision"] == "GAP_FOLLOW_CONTINUATION"


def test_momentum_lowvol_basket():
    """Verify Qlib Momentum + Riskfolio Low-Vol selection."""
    res = select_momentum_lowvol_basket()
    assert len(res["selected_assets"]) > 0
    assert "portfolio_weights" in res
    assert sum(res["portfolio_weights"].values()) == pytest.approx(1.0, abs=1e-2)


def test_pairs_trading_spread_and_signal():
    """Verify HDFCBANK vs ICICIBANK spread z-score divergence."""
    sig = generate_pairs_trading_signal(price_hdfc=1650.0, price_icici=1240.0, z_score=2.2)
    assert sig["signal"] == "DIVERGED_LONG_B_SHORT_A"
    assert "BUY_LONG ICICIBANK" in sig["leg_icici_action"]


def test_crypto_basis_funding_arbitrage():
    """Verify Binance funding rate > 0.1% triggers basis cash-and-carry."""
    edge = evaluate_crypto_funding_edge({"funding_rate_8h_pct": 0.15, "annualized_rate_pct": 164.0, "mark_price": 86900.0})
    assert edge["signal"] == "CROWDED_LONGS_SHORT_EDGE"
    assert "DELTA_NEUTRAL_CASH_CARRY" in edge["action"]


def test_0dte_theta_strangle():
    """Verify 0DTE 1.5% OTM strangle strike generation and decay."""
    strangle = generate_0dte_strangle_strikes(spot_price=22100.0)
    assert strangle["ce_strike"] > 22100
    assert strangle["pe_strike"] < 22100
    assert strangle["stop_loss_ce_prem"] == pytest.approx(strangle["ce_estimated_premium"] * 2.0)

    decay = simulate_0dte_decay(starting_premium=20.0, minutes_remaining=45)
    assert decay["final_projected_premium"] < 20.0
    assert decay["captured_theta_pct"] > 50.0


# ==============================================================================
# 3. BIASES ALERTS TESTS
# ==============================================================================
def test_all_five_biases():
    """Verify detection of the 5 fatal cognitive biases."""
    b1 = check_disposition_effect(current_pnl_pct=-8.0, holding_duration_mins=120)
    assert b1["triggered"] is True

    b2 = check_overnight_risk_bias(is_intraday_strategy=True, current_time_str="15:25", position_pnl_pct=-3.0, holding_overnight=True)
    assert b2["triggered"] is True

    b3 = check_recency_bias(consecutive_green_days=3)
    assert b3["triggered"] is True

    b4 = check_lottery_bias(stock_price=22.0)
    assert b4["triggered"] is True

    b5 = check_anchoring_bias(nominal_drop_pct=25.0, earnings_momentum_pct=-10.0)
    assert b5["triggered"] is True


# ==============================================================================
# 4. TOOLKIT METRICS TESTS
# ==============================================================================
def test_atr_sizing_and_toolkit():
    """Verify 1% risk budgeting and correlation clustering."""
    sizing = atr_position_sizing(capital=100_000.0, risk_pct=0.01, current_price=2000.0, atr=20.0, stop_multiplier=1.5)
    # Risk budget = 1000. Stop distance = 30. Recommended shares = floor(1000/30) = 33
    assert sizing["recommended_shares"] == 33
    assert sizing["risk_budget_inr"] == 1000.0

    rsi_res = rsi_volume_confirmation()
    assert "status" in rsi_res

    corr_res = correlation_cluster_check()
    assert corr_res["is_concentrated_illusion"] is True

    bt_filter = backtest_quality_filter(trades_count=220, sharpe_gross=1.8, fee_drag_pct=20.0)
    assert bt_filter["is_institutionally_viable"] is True


# ==============================================================================
# 5. STARTER PAPER SYSTEM TESTS
# ==============================================================================
def test_mumbai_starter_paper_system():
    """Verify end-to-end 30-day paper trading system execution and positive expectancy."""
    sys = MumbaiStarterPaperSystem(initial_capital=100_000.0)
    cand = sys.evaluate_live_candidate(current_price=22120.0, ema_20=22010.0, orb_high=22100.0)
    assert cand["decision"] == "APPROVED_BUY_ENTRY"
    assert cand["status"] == "APPROVED"

    ledger = sys.generate_starter_30_days_ledger()
    assert ledger["total_trades"] == 30
    assert ledger["win_rate_pct"] > 50.0
    assert ledger["expectancy_r"] > 0.0
    assert ledger["is_edge_positive"] is True
    assert ledger["total_pnl_inr"] > 0
