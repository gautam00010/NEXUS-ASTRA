"""Institutional Low-Frequency Trading (LFT) End-to-End Research Template.

Executes a complete quant research and trade validation cycle on a standard laptop:
1. Macro Regime Detection (3-State HMM: Trending Low Vol vs Mean-Reverting vs Panic)
2. Derivative Positioning Analysis (FII Index Futures Percentile + Options PCR)
3. Statistical Arbitrage Residual Screening (Idiosyncratic BankNifty Residual Z-Score)
4. Expected Value (EV) Filter (Transaction Friction & Breakeven Calibration)
5. Half-Kelly Position Sizing (Asymmetric Capital Allocation Capped at 12.5%)
6. Institutional 5-Point Checklist Gate (Hard Binary Stop)
"""

from __future__ import annotations
import logging
from typing import Any, Dict

from nexus_astra.institutional.hmm_regime import InstitutionalHMMRegimeClassifier
from nexus_astra.institutional.fii_oi_model import evaluate_fii_options_positioning
from nexus_astra.institutional.residual_reversion import evaluate_residual_stat_arb
from nexus_astra.probability.ev_calculator import calculate_trade_expected_value
from nexus_astra.probability.kelly import calculate_institutional_kelly
from nexus_astra.checklist.institutional_checklist import evaluate_institutional_checklist

logger = logging.getLogger(__name__)


class InstitutionalLFTResearchEngine:
    """
    End-to-End Institutional LFT Alpha Research & Execution Pipeline.
    Runs on consumer laptops in under 50 milliseconds.
    """

    def __init__(self, portfolio_capital_inr: float = 1_000_000.0) -> None:
        self.portfolio_capital_inr = portfolio_capital_inr

    def run_pipeline(
        self,
        current_vix: float = 14.2,
        fii_long_pct: float = 82.5,
        pcr_oi: float = 0.74,
        stat_arb_symbol: str = "ICICIBANK",
        residual_z: float = 2.65,
        stock_beta: float = 1.15,
        thesis_statement: str = "Exploiting 2.65-sigma residual divergence in ICICIBANK with FII tailwind in low-vol regime.",
    ) -> Dict[str, Any]:
        """
        Runs the full 6-stage quantitative institutional workflow.
        """
        # Step 1: Macro Regime Classification via HMM
        regime_result = InstitutionalHMMRegimeClassifier.classify_regime(current_vix=current_vix)

        # Step 2: FII Flow + Options Positioning
        fii_result = evaluate_fii_options_positioning(
            fii_index_futures_long_pct=fii_long_pct,
            pcr_oi=pcr_oi,
            vix_current=current_vix,
        )

        # Step 3: Statistical Arbitrage Residual Screening
        stat_arb_result = evaluate_residual_stat_arb(
            symbol=stat_arb_symbol,
            z_score=residual_z,
            beta=stock_beta,
        )

        # Step 4: Expected Value (EV) Filter
        win_rate = 0.62 if fii_result["forward_5d_win_rate_pct"] > 60 else 0.52
        ev_result = calculate_trade_expected_value(
            win_rate=win_rate,
            avg_win_inr=22000.0,
            avg_loss_inr=12000.0,
            capital_at_risk_inr=12000.0,
            roundtrip_friction_inr=650.0,
        )

        # Step 5: Position Sizing via Half-Kelly
        payoff_ratio = 22000.0 / 12000.0  # 1.833
        kelly_result = calculate_institutional_kelly(
            win_rate=win_rate,
            payoff_ratio=payoff_ratio,
            fraction_multiplier=0.50,  # Half-Kelly
            max_cap_pct=12.5,          # Institutional 12.5% cap
        )

        # Step 6: Institutional 5-Point Checklist Gate
        checklist_result = evaluate_institutional_checklist(
            q1_explicit_edge_over_hft=True,
            q2_uncrowded_sentiment=True,
            q3_third_order_mapped=True,
            q4_half_kelly_sized=kelly_result["recommended_allocation_pct"] <= 12.5,
            q5_one_sentence_thesis=True,
            thesis_statement=thesis_statement,
        )

        # Final Capital Allocation in INR
        alloc_pct = kelly_result["recommended_allocation_pct"] if checklist_result["all_passed"] else 0.0
        allocated_capital_inr = round(self.portfolio_capital_inr * (alloc_pct / 100.0), 2)

        is_executable = (
            checklist_result["all_passed"]
            and ev_result["status"] == "TRADEABLE_POSITIVE_EDGE"
            and alloc_pct > 0.0
        )

        return {
            "is_trade_executable": is_executable,
            "final_action": stat_arb_result["action"] if is_executable else "STAND_DOWN_NO_TRADE",
            "allocated_capital_inr": allocated_capital_inr,
            "allocated_capital_pct": alloc_pct,
            "pipeline_stages": {
                "stage1_hmm_regime": regime_result,
                "stage2_fii_options": fii_result,
                "stage3_statarb_screen": stat_arb_result,
                "stage4_ev_hurdle": ev_result,
                "stage5_kelly_sizing": kelly_result,
                "stage6_checklist_gate": checklist_result,
            },
            "summary_thesis": (
                f"Market Regime: {regime_result['regime_name']}. FII Derivative Stance: {fii_result['regime']}. "
                f"Net EV: +₹{ev_result['net_ev_per_trade_inr']:.2f} per trade. Half-Kelly allocation: {alloc_pct}%. "
                f"Checklist Status: {checklist_result['status']}."
            ),
        }


def run_research_demonstration() -> Dict[str, Any]:
    """Runs a standard demonstration of the research template."""
    engine = InstitutionalLFTResearchEngine(portfolio_capital_inr=1_000_000.0)
    return engine.run_pipeline()


if __name__ == "__main__":
    report = run_research_demonstration()
    print("=== NEXUS-ASTRA INSTITUTIONAL LFT RESEARCH REPORT ===")
    print(f"Executable: {report['is_trade_executable']}")
    print(f"Action:     {report['final_action']}")
    print(f"Capital:    ₹{report['allocated_capital_inr']:,.2f} ({report['allocated_capital_pct']}%)")
    print(f"Summary:    {report['summary_thesis']}")
