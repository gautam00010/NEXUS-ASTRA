"""Top 10 Institutional LFT Models (Holding Horizions: Hours to Weeks).

Modules:
1. Cross-Sectional Momentum Risk Model (12-1M Return/Vol, Riskfolio HRP, Sharpe 1.5-2.0)
2. FII Flow + Options Positioning (80th percentile FII long, PCR < 0.80, VIX falling, 62% win rate)
3. Earnings Revision Drift (ERD: 3+ analysts revise EPS > 5%, 20-30 day drift +8%)
4. Intraday Volume Profile + Delta Imbalance (POC, VAH, VAL, cumulative delta > +2M)
5. Crypto-Equity Regime (BTC Dominance < 54% + stablecoin expansion leads Indian midcaps by 48h)
6. BankNifty StatArb Residual Reversion (OLS beta residual z-score > 2.5, 3-5 day reversion)
7. RBI Policy & Inflation Surprise Event-Driven (Hawkish surprise -> PSU bank NIM expansion 2-3 weeks)
8. Volatility Risk Premium Harvest (IV > RV 85% of time, sell 10Δ strangle 30 DTE, active only VIX > 20, max 15%)
9. Microstructure Spread Capture (BSE smallcap 1-2% spread during 09:30-10:30 AM passive limit)
10. AI Ensemble Regime-Switching HMM (3-state Hidden Markov Model: Trending Low Vol / Mean-Reverting / High Vol Panic)
"""

from __future__ import annotations
from typing import Any, Dict

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


def run_institutional_lft_suite() -> Dict[str, Any]:
    """
    Runs all 10 Institutional LFT models and generates a comprehensive master assessment.
    """
    m1 = compute_cross_sectional_momentum_basket()
    m2 = evaluate_fii_options_positioning()
    m3 = evaluate_earnings_revision_drift()
    m4 = evaluate_volume_profile_imbalance()
    m5 = evaluate_crypto_equity_lead_lag()
    m6 = evaluate_residual_stat_arb()
    m7 = evaluate_rbi_policy_event()
    m8 = evaluate_vrp_harvest()
    m9 = evaluate_bse_liquidity_provision()
    m10 = InstitutionalHMMRegimeClassifier.classify_regime()

    return {
        "m1_cross_sectional_momentum": m1,
        "m2_fii_oi_flow": m2,
        "m3_erd_drift": m3,
        "m4_volume_profile_delta": m4,
        "m5_crypto_equity_regime": m5,
        "m6_residual_stat_arb": m6,
        "m7_rbi_event_psu_nim": m7,
        "m8_vrp_strangle_harvest": m8,
        "m9_bse_liquidity_spread": m9,
        "m10_hmm_regime_switch": m10,
        "summary": {
            "regime": m10["regime_name"],
            "fii_stance": m2["regime"],
            "equity_exposure_recommended_pct": m10["recommended_equity_exposure_pct"],
            "top_momentum_pick": m1.get("top_decile_longs", ["N/A"])[0] if m1.get("top_decile_longs") else "N/A",
            "stat_arb_signal": m6["signal"],
        }
    }


__all__ = [
    "compute_cross_sectional_momentum_basket",
    "evaluate_fii_options_positioning",
    "evaluate_earnings_revision_drift",
    "compute_volume_profile_nodes",
    "evaluate_volume_profile_imbalance",
    "evaluate_crypto_equity_lead_lag",
    "compute_stock_index_residual",
    "evaluate_residual_stat_arb",
    "evaluate_rbi_policy_event",
    "evaluate_vrp_harvest",
    "evaluate_bse_liquidity_provision",
    "InstitutionalHMMRegimeClassifier",
    "run_institutional_lft_suite",
]
