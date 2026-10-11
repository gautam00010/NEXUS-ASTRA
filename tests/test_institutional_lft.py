"""Comprehensive Test Suite for Institutional LFT Exponential Architecture.

Validates:
1. Game Theory Edge vs HFT & 3rd-Order Failed Gap Fade
2. Top 10 Institutional LFT Models (Cross-Sectional Momentum, FII OI, ERD, Volume Profile,
   Crypto-Equity, StatArb Residual, RBI Event, VRP Harvest, BSE Spread, HMM 3-State Regime)
3. Advanced Probabilities (Kelly 25% / Half 12.5%, Bayes Base Rate 8% -> 23.3%, EV with STT Friction, Second-Order Stats)
4. Top 2% Philosophy (Ergodicity -50%->+100%, Soros Reflexivity, Antifragile 80/20 Barbell, Loser's Game)
5. Institutional 5-Question Pre-Trade Checklist (Hard Binary Filter)
6. End-to-End LFT Research Pipeline
7. Composite Signal Orchestrator Institutional Integration
"""

import pytest
import numpy as np
import pandas as pd

from nexus_astra.game_theory.edge_vs_hft import explicit_edge_vs_hft
from nexus_astra.game_theory.order_thinking import third_order_signal
from nexus_astra.institutional.cross_sectional_momentum import compute_cross_sectional_momentum_basket
from nexus_astra.institutional.fii_oi_model import evaluate_fii_options_positioning
from nexus_astra.institutional.erd import evaluate_earnings_revision_drift
from nexus_astra.institutional.volume_profile import compute_volume_profile_nodes, evaluate_volume_profile_imbalance
from nexus_astra.institutional.crypto_equity_regime import evaluate_crypto_equity_lead_lag
from nexus_astra.institutional.residual_reversion import compute_stock_index_residual, evaluate_residual_stat_arb
from nexus_astra.institutional.event_rbi import evaluate_rbi_policy_event
from nexus_astra.institutional.vrp_harvest import evaluate_vrp_harvest
from nexus_astra.institutional.bse_liquidity import evaluate_bse_liquidity_provision
from nexus_astra.institutional.hmm_regime import InstitutionalHMMRegimeClassifier
from nexus_astra.institutional import run_institutional_lft_suite
from nexus_astra.probability.kelly import calculate_institutional_kelly
from nexus_astra.probability.bayes_base_rate import compute_bayesian_posterior
from nexus_astra.probability.ev_calculator import calculate_trade_expected_value
from nexus_astra.probability.second_order_stats import compute_second_order_statistics
from nexus_astra.philosophy.ergodicity import compute_ergodicity_recovery_burden
from nexus_astra.philosophy.reflexivity import evaluate_soros_reflexivity_drag
from nexus_astra.philosophy.antifragile import compute_antifragile_barbell_allocation
from nexus_astra.philosophy.losers_game import evaluate_unforced_error_risk
from nexus_astra.checklist.institutional_checklist import evaluate_institutional_checklist
from nexus_astra.research.lft_template import InstitutionalLFTResearchEngine, run_research_demonstration
from nexus_astra.signal_engine.composite_orchestrator import SignalOrchestrator


class TestGameTheory:
    def test_sub_second_latency_has_no_edge(self):
        res = explicit_edge_vs_hft(holding_period_days=0, capital_deployed_cr=0.1)
        assert res["decision"] == "DON'T_TRADE"
        assert res["edge_exists"] is False
        assert "SUB_SECOND" in res["holding_horizon"]

    def test_multi_day_slow_alpha_has_structural_edge(self):
        res = explicit_edge_vs_hft(holding_period_days=5, capital_deployed_cr=2.0)
        assert res["decision"] == "PROCEED_LFT_EXECUTION"
        assert res["edge_exists"] is True
        assert res["edge_classification"] == "SLOW_ALPHA_MACRO_FLOW"

    def test_third_order_failed_gap_fade_explosion(self):
        # Gap > 1.2% + FII Long Futures > 80% + BankNifty not confirming fade
        res = third_order_signal(
            gap_pct=1.35,
            fii_long_futures_percentile=84.0,
            banknifty_confirms_fade=False,
        )
        assert res["action"] == "LONG_FAILED_FADE_TREND_EXPANSION"
        assert res["third_order_institutional"]["failed_fade_confirmed"] is True
        assert res["win_rate_expectancy_pct"] >= 64.0

    def test_standard_gap_fades_normally(self):
        # Normal gap without FII institutional commitment
        res = third_order_signal(
            gap_pct=0.85,
            fii_long_futures_percentile=45.0,
            banknifty_confirms_fade=True,
        )
        assert res["action"] == "SHORT_FADE_OPEN_AT_10_30_AM"
        assert res["third_order_institutional"]["failed_fade_confirmed"] is False


class TestTop10InstitutionalModels:
    def test_cross_sectional_momentum_basket(self):
        res = compute_cross_sectional_momentum_basket()
        assert "top_decile_longs" in res
        assert "bottom_decile_shorts" in res
        assert len(res["top_decile_longs"]) > 0
        assert res["target_sharpe_range"] == "1.5 - 2.0"

    def test_fii_options_positioning_bullish_asymmetry(self):
        res = evaluate_fii_options_positioning(
            fii_index_futures_long_pct=85.0,
            pcr_oi=0.72,
            vix_current=13.5,
            vix_5d_change_pct=-4.0,
        )
        assert res["regime"] == "HIGH_CONVICTION_INSTITUTIONAL_BULL"
        assert res["forward_5d_win_rate_pct"] == 62.0
        assert res["expected_payoff"] == "1.8:1"

    def test_earnings_revision_drift(self):
        res = evaluate_earnings_revision_drift(
            symbol="TCS",
            analysts_upward_revisions_count=4,
            consensus_eps_revision_pct=6.5,
        )
        assert res["status"] in ["APPROVED_ERD_DRIFT_LONG", "ERD_SIGNAL_QUALIFIED"]
        assert res["action"] == "LONG_ERD_SWING"
        assert res["projected_drift_pct"] >= 7.0

    def test_volume_profile_and_cumulative_delta(self):
        nodes = compute_volume_profile_nodes(
            prices=np.linspace(22000, 22200, 100),
            volumes=np.ones(100) * 1000,
        )
        assert "poc" in nodes and "vah" in nodes and "val" in nodes
        assert nodes["vah"] >= nodes["val"]

        imbal = evaluate_volume_profile_imbalance(
            current_price=22180.0,
            prev_vah=22120.0,
            cumulative_delta_shares=2_500_000.0,
        )
        assert imbal["signal"] == "LONG_ACCEPTANCE_ABOVE_VAH"

    def test_crypto_equity_regime(self):
        res = evaluate_crypto_equity_lead_lag(
            btc_dominance_pct=52.5,
            stablecoin_mcap_14d_pct=3.5,
        )
        assert res["regime_classification"] == "HIGH_BETA_RISK_ON"
        assert "MIDCAP" in res["nse_positioning_stance"]


    def test_residual_stat_arb(self):
        np.random.seed(42)
        idx_ret = np.random.normal(0.0005, 0.01, 100)
        stock_ret = 1.15 * idx_ret + np.random.normal(0.0, 0.005, 100)
        decomp = compute_stock_index_residual(stock_ret, idx_ret)
        assert "alpha" in decomp and "beta" in decomp and "current_residual_z" in decomp

        arb_res = evaluate_residual_stat_arb(symbol="ICICIBANK", z_score=2.65, beta=1.15)
        assert arb_res["signal"] == "SHORT_STOCK_LONG_INDEX_BETA"

    def test_rbi_event_psu_nim(self):
        res = evaluate_rbi_policy_event(rate_surprise_bps=25.0, cpi_inflation_pct=5.5)
        assert res["signal"] == "LONG_PSU_BANKS_SWING"
        assert "SBIN" in res["recommended_basket"]

    def test_vrp_harvest_vix_gate(self):
        # When VIX < 20, VRP harvest must STAND DOWN
        res_calm = evaluate_vrp_harvest(vix_current=14.0)
        assert res_calm["status"] == "STAND_DOWN_VIX_TOO_LOW"
        assert res_calm["recommended_allocation_pct"] == 0.0

        # When VIX >= 20 and IV > RV, VRP harvest executes with max 15% cap
        res_elevated = evaluate_vrp_harvest(iv_30d_pct=24.0, rv_30d_pct=16.0, vix_current=21.5)
        assert res_elevated["status"] == "EXECUTE_VRP_HARVEST"
        assert res_elevated["recommended_allocation_pct"] <= 15.0

    def test_bse_microstructure_spread_window(self):
        # Inside 09:30 - 10:30 AM with 1.5% spread
        res = evaluate_bse_liquidity_provision(
            bid_price=245.0, ask_price=248.65, current_time_str="09:45"
        )
        assert res["action"] == "POST_PASSIVE_LIMIT_ORDERS"
        assert res["expected_net_capture_bps"] > 0

    def test_hmm_regime_classification(self):
        res = InstitutionalHMMRegimeClassifier.classify_regime(current_vix=13.5)
        assert res["current_state_index"] == 0
        assert res["regime_name"] == "TRENDING_LOW_VOL"
        assert res["recommended_equity_exposure_pct"] == 100.0

    def test_institutional_suite_runner(self):
        suite = run_institutional_lft_suite()
        assert "m1_cross_sectional_momentum" in suite
        assert "m10_hmm_regime_switch" in suite
        assert "summary" in suite


class TestAdvancedProbabilities:
    def test_kelly_exact_formula(self):
        # 55% win rate, 1:1.5 payoff ratio (b = 1.5)
        # f* = (0.55 * 2.5 - 1) / 1.5 = (1.375 - 1) / 1.5 = 0.375 / 1.5 = 0.25 (25.0%)
        # Half-Kelly = 12.5%
        res = calculate_institutional_kelly(
            win_rate=0.55,
            payoff_ratio=1.50,
            fraction_multiplier=0.50,
            max_cap_pct=12.5,
        )
        assert res["full_kelly_pct"] == 25.0
        assert res["half_kelly_pct"] == 12.5
        assert res["recommended_allocation_pct"] == 12.5

    def test_bayesian_base_rate_updating(self):
        # Prior 8.0%, True Positive 70%, False Positive 20%
        # P(Double | Signal) = (0.70 * 0.08) / (0.70*0.08 + 0.20*0.92) = 0.056 / 0.24 = 23.33%
        res = compute_bayesian_posterior(
            prior_base_rate=0.08,
            true_positive_rate=0.70,
            false_positive_rate=0.20,
        )
        assert abs(res["true_posterior_probability_pct"] - 23.33) < 0.05
        assert res["prior_base_rate_pct"] == 8.0

    def test_ev_calculator_with_indian_friction(self):
        res = calculate_trade_expected_value(
            win_rate=0.52,
            avg_win_inr=24000.0,
            avg_loss_inr=12000.0,
            roundtrip_friction_inr=650.0,
        )
        assert res["status"] == "TRADEABLE_POSITIVE_EDGE"
        assert res["net_ev_per_trade_inr"] > 0
        assert res["breakeven_win_rate_pct"] < 52.0

    def test_second_order_statistics(self):
        res = compute_second_order_statistics()
        assert res["autocorrelation_lag1"] > 0.25
        assert res["pnl_skewness"] > 0.50
        assert res["optimal_stop_loss_pct"] > 0


class TestTop2PercentPhilosophy:
    def test_ergodicity_recovery_asymmetry(self):
        res_50 = compute_ergodicity_recovery_burden(current_drawdown_pct=50.0)
        assert res_50["required_recovery_gain_pct"] == 100.0

        res_80 = compute_ergodicity_recovery_burden(current_drawdown_pct=80.0)
        assert res_80["required_recovery_gain_pct"] == 400.0

    def test_soros_reflexivity_issuance_drag(self):
        res = evaluate_soros_reflexivity_drag(
            nifty_pe=24.5,
            monthly_primary_issuance_cr=30000.0,
            dii_monthly_sip_cr=22000.0,
        )
        assert res["reflexivity_phase"] == "EXCESS_PAPER_SUPPLY_OVERHANG"
        assert res["risk_level"] == "ELEVATED_STRUCTURAL_DRAG"

    def test_antifragile_barbell_allocation(self):
        res = compute_antifragile_barbell_allocation(total_capital_inr=1_000_000.0)
        assert res["safe_capital_inr"] == 800_000.0
        assert res["convex_capital_inr"] == 200_000.0
        # In severe crash, total portfolio gains from convex options
        assert res["scenarios"]["severe_crash_minus_35pct"]["total_portfolio_pnl_pct"] > 0

    def test_losers_game_avoids_unforced_errors(self):
        res_bad = evaluate_unforced_error_risk(setup_conviction_stars=2, market_volatility_clarity="CHOP")
        assert res_bad["decision"] == "STAND_DOWN_DO_NOT_TRADE"
        assert res_bad["should_skip_trading"] is True


class TestChecklistAndResearchTemplate:
    def test_institutional_checklist_all_passed(self):
        res = evaluate_institutional_checklist(
            q1_explicit_edge_over_hft=True,
            q2_uncrowded_sentiment=True,
            q3_third_order_mapped=True,
            q4_half_kelly_sized=True,
            q5_one_sentence_thesis=True,
            thesis_statement="Capturing 20-day post-earnings drift in TCS driven by 4 consensus upward analyst revisions.",
        )
        assert res["status"] == "APPROVED_FOR_EXECUTION"
        assert res["all_passed"] is True
        assert res["passed_count"] == 5

    def test_institutional_checklist_any_failure_blocks_trade(self):
        res = evaluate_institutional_checklist(
            q1_explicit_edge_over_hft=False,  # Failed edge vs HFT
            q2_uncrowded_sentiment=True,
            q3_third_order_mapped=True,
            q4_half_kelly_sized=True,
            q5_one_sentence_thesis=True,
        )
        assert res["status"] == "DON'T_TRADE"
        assert res["all_passed"] is False
        assert "Q1_Explicit_Edge_vs_HFT" in res["failed_questions"]

    def test_end_to_end_research_pipeline(self):
        engine = InstitutionalLFTResearchEngine(portfolio_capital_inr=1_000_000.0)
        report = engine.run_pipeline()
        assert report["is_trade_executable"] is True
        assert report["allocated_capital_pct"] <= 12.5
        assert report["allocated_capital_inr"] <= 125_000.0
        assert "stage1_hmm_regime" in report["pipeline_stages"]

    def test_signal_orchestrator_institutional_sleeve(self):
        orch = SignalOrchestrator()
        sleeve = orch.evaluate_institutional_exponential_sleeve(
            symbol="NIFTY",
            gap_pct=1.35,
            fii_long_pct=84.0,
            banknifty_confirms_fade=False,
            thesis_statement="Institutional LFT regime edge with FII flow confirmation.",
        )
        assert sleeve["decision"] == "APPROVED"
        assert sleeve["recommended_allocation_pct"] <= 12.5
        assert sleeve["third_order"]["action"] == "LONG_FAILED_FADE_TREND_EXPANSION"
