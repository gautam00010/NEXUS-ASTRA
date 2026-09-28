"""Paper Trading Verification Gate to prevent untested deployment."""

from __future__ import annotations

import logging
from datetime import date
from typing import Dict, Any, List

from nexus_astra.data_ingestion.database import PaperTradingGateState, database_manager

logger = logging.getLogger(__name__)


class PaperTradingGate:
    """Rigorous staging environment to gate live capital deployment."""

    def __init__(self) -> None:
        pass

    def go_live_criteria(self, paper_results: Dict[str, Any]) -> bool:
        """
        Returns True ONLY if strict backtest/paper thresholds are met.
        """
        sharpe = paper_results.get("sharpe", 0.0)
        max_dd = paper_results.get("max_drawdown", 1.0)
        win_rate = paper_results.get("win_rate", 0.0)
        expectancy = paper_results.get("expectancy", 0.0)
        total_signals = paper_results.get("total_signals", 0)
        last_10_outcomes = paper_results.get("last_10_outcomes", []) # list of booleans (True=Win)
        
        if sharpe <= 1.2:
            logger.info(f"Failed Go-Live: Sharpe {sharpe:.2f} <= 1.2")
            return False
            
        if max_dd >= 0.15:
            logger.info(f"Failed Go-Live: Max Drawdown {max_dd*100:.1f}% >= 15%")
            return False
            
        if win_rate <= 0.55:
            logger.info(f"Failed Go-Live: Win Rate {win_rate*100:.1f}% <= 55%")
            return False
            
        if expectancy <= 0.6:
            logger.info(f"Failed Go-Live: Expectancy {expectancy:.2f} <= 0.6")
            return False
            
        if total_signals < 30:
            logger.info(f"Failed Go-Live: Total Signals {total_signals} < 30")
            return False
            
        losses_in_last_10 = len([x for x in last_10_outcomes if not x])
        if losses_in_last_10 < 2:
            logger.info(f"Failed Go-Live: Must have seen drawdown behavior (only {losses_in_last_10} losses in last 10)")
            return False
            
        logger.info("GO-LIVE CRITERIA PASSED.")
        return True

    def gradual_capital_deployment(self, month_index: int, prior_months_profitable: bool) -> float:
        """
        Controls scaling of deployed capital post-gate.
        month_index: 1 for first month live, etc.
        """
        if month_index == 1:
            return 0.10
        elif month_index == 2:
            return 0.25 if prior_months_profitable else 0.10
        elif month_index == 3:
            return 0.50 if prior_months_profitable else 0.25
        elif month_index >= 4:
            return 1.00 if prior_months_profitable else 0.50
            
        return 0.0

    def live_monitoring(self, live_pnl: float, paper_pnl: float) -> str:
        """
        After going live, compare live P&L to paper P&L weekly.
        If divergence > 20% (live underperforming) -> SLIPPAGE_ISSUE
        """
        if paper_pnl <= 0:
            return "NORMAL"
            
        divergence = (paper_pnl - live_pnl) / paper_pnl
        
        if divergence > 0.20:
            logger.warning(f"MARKET_IMPACT / SLIPPAGE_ISSUE ALERT: Live PnL is lagging Paper by {divergence*100:.1f}%")
            return "SLIPPAGE_ISSUE"
            
        return "NORMAL"

    def kill_switch(self, live_drawdown: float, live_sharpe_history: List[float]) -> bool:
        """
        If live drawdown hits 15% OR live Sharpe drops below 0.8 for 2 months -> automatic halt.
        """
        if live_drawdown >= 0.15:
            logger.critical("KILL SWITCH TRIGGERED: Live Max Drawdown hit 15%.")
            return True
            
        if len(live_sharpe_history) >= 2:
            last_2_months = live_sharpe_history[-2:]
            if all(s < 0.8 for s in last_2_months):
                logger.critical("KILL SWITCH TRIGGERED: Live Sharpe < 0.8 for 2 consecutive months.")
                return True
                
        return False

    def process_gate(
        self, 
        current_date: date,
        paper_results: Dict[str, Any],
        live_month_index: int,
        prior_profitable: bool,
        live_drawdown: float,
        live_sharpe_history: List[float]
    ) -> Dict[str, Any]:
        """
        Full orchestration of the gate state.
        """
        stage = "PAPER"
        deploy_pct = 0.0
        
        passed_gate = self.go_live_criteria(paper_results)
        
        if passed_gate:
            killed = self.kill_switch(live_drawdown, live_sharpe_history)
            if killed:
                stage = "HALTED"
                deploy_pct = 0.0
            else:
                stage = f"LIVE_M{live_month_index}" if live_month_index < 4 else "LIVE_FULL"
                deploy_pct = self.gradual_capital_deployment(live_month_index, prior_profitable)
        
        with database_manager.session_scope() as session:
            record = PaperTradingGateState(
                date=current_date,
                stage=stage,
                sharpe_ratio=paper_results.get("sharpe", 0.0),
                max_drawdown=paper_results.get("max_drawdown", 0.0),
                capital_deployment_pct=deploy_pct
            )
            session.add(record)
            
        return {
            "passed_gate": passed_gate,
            "stage": stage,
            "deploy_pct": deploy_pct
        }
