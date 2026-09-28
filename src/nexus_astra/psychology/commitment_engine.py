"""Pre-Commitment Contract Engine for psychological safety and risk guardrails."""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import date, timedelta
from typing import Dict, Any, List

import polars as pl
from dataclasses import asdict, is_dataclass

from nexus_astra.data_ingestion.database import PsychologyLog, database_manager

logger = logging.getLogger(__name__)


class PreCommitmentContract:
    """Psychological guardrails and contract logic."""

    def __init__(self) -> None:
        self.active_contract: Dict[str, Any] | None = None

    def create_contract(
        self, 
        capital: float, 
        max_drawdown_pct: float = 15.0, 
        max_drawdown_duration_months: int = 3, 
        min_win_rate_months: int = 2, 
        min_sharpe: float = 1.2
    ) -> Dict[str, Any]:
        """Generate a signed (hashed) contract dict with rules."""
        
        rules = {
            "capital_base": capital,
            "max_drawdown_pct": max_drawdown_pct,
            "max_drawdown_duration_months": max_drawdown_duration_months,
            "min_win_rate_months": min_win_rate_months,
            "min_sharpe": min_sharpe,
            "date_created": date.today().isoformat()
        }
        
        rules_str = json.dumps(rules, sort_keys=True)
        contract_hash = hashlib.sha256(rules_str.encode("utf-8")).hexdigest()
        
        self.active_contract = {
            "rules": rules,
            "signature_hash": contract_hash,
            "status": "ENFORCED"
        }
        
        with database_manager.session_scope() as session:
            session.add(PsychologyLog(
                date=date.today(),
                log_type="CONTRACT",
                details=json.dumps(self.active_contract)
            ))
            
        logger.info(f"Pre-commitment contract signed. Hash: {contract_hash[:8]}")
        return self.active_contract

    def check_breach(
        self, 
        current_drawdown: float, 
        drawdown_duration_months: float, 
        win_rate_last_2_months: float, 
        sharpe_current: float
    ) -> str:
        """
        Returns GREEN, YELLOW (approaching limit), or RED (breach).
        """
        if not self.active_contract:
            logger.warning("No active contract to enforce! Defaulting to RED.")
            return "RED"
            
        rules = self.active_contract["rules"]
        max_dd = rules["max_drawdown_pct"]
        max_dd_dur = rules["max_drawdown_duration_months"]
        min_sharpe = rules["min_sharpe"]
        
        # 1. Breach logic (RED)
        if (current_drawdown >= max_dd) or \
           (drawdown_duration_months >= max_dd_dur) or \
           (sharpe_current < min_sharpe - 0.5): # e.g. sharply below min
            status = "RED"
            details = "Contract breached! Manual restart required."
            
        # 2. Warning logic (YELLOW) - approaching limits (e.g. 80% of limit)
        elif (current_drawdown >= max_dd * 0.8) or \
             (drawdown_duration_months >= max_dd_dur * 0.8) or \
             (sharpe_current <= min_sharpe):
            status = "YELLOW"
            details = "Approaching limits. Recommend reduce size 50%."
            
        # 3. All clear (GREEN)
        else:
            status = "GREEN"
            details = "All metrics within contract bounds."
            
        with database_manager.session_scope() as session:
            session.add(PsychologyLog(
                date=date.today(),
                log_type="BREACH_CHECK",
                details=f"Status: {status}. {details}"
            ))
            
        return status

    def winning_streak_guard(self, consecutive_wins: int) -> float:
        """
        After 4 consecutive wins, automatically reduce position size by 20% for next 2 trades.
        Returns size multiplier (1.0 or 0.8).
        """
        if consecutive_wins >= 4:
            multiplier = 0.80
            msg = f"Winning streak guard activated ({consecutive_wins} wins). Size reduced from 100% to 80%."
            logger.info(msg)
            
            with database_manager.session_scope() as session:
                session.add(PsychologyLog(
                    date=date.today(),
                    log_type="WIN_STREAK",
                    metric_value=consecutive_wins,
                    details=msg
                ))
            return multiplier
            
        return 1.0

    def daily_anchor_check(self, position_symbol: str, would_signal_fresh_today: bool) -> bool:
        """
        Ask: 'Given current market info, would system signal this trade fresh today?'
        If no, trigger EXIT_ANCHOR_BROKEN alert.
        Returns False if broken (needs exit), True if valid.
        """
        if not would_signal_fresh_today:
            msg = f"EXIT_ANCHOR_BROKEN: Would not signal {position_symbol} fresh today. Breaking psychological anchor."
            logger.warning(msg)
            
            with database_manager.session_scope() as session:
                session.add(PsychologyLog(
                    date=date.today(),
                    log_type="ANCHOR_CHECK",
                    details=msg
                ))
            return False
            
        return True

    def process_quality_logger(self, signal_id: str, decision_quality_score: float, pnl: float) -> None:
        """
        Log process quality (1-10) independent of P&L.
        """
        with database_manager.session_scope() as session:
            session.add(PsychologyLog(
                date=date.today(),
                log_type="PROCESS_QUALITY",
                signal_id=signal_id,
                metric_value=decision_quality_score,
                details=f"PnL: {pnl}"
            ))
            
        logger.info(f"Process quality {decision_quality_score}/10 logged for signal {signal_id}.")

    def generate_weekly_report(self) -> str:
        """
        Generate weekly behavioral report.
        """
        cutoff = date.today() - timedelta(days=7)
        
        with database_manager.session_scope() as session:
            rows = session.query(PsychologyLog).filter(PsychologyLog.date >= cutoff).all()
            
        if not rows:
            return "No behavioral data for the past week."
            
        records = []
        for row in rows:
            record = asdict(row) if is_dataclass(row) else row.__dict__.copy()
            record.pop("_sa_instance_state", None)
            records.append(record)
            
        df = pl.DataFrame(records)
        
        # Analyze process vs outcome
        pq_logs = df.filter(pl.col("log_type") == "PROCESS_QUALITY")
        variance_msg = ""
        
        if not pq_logs.is_empty():
            # Parse PnL from details (format: "PnL: X")
            def extract_pnl(s):
                try:
                    return float(s.replace("PnL: ", ""))
                except:
                    return 0.0
                    
            pq_logs = pq_logs.with_columns(
                pl.col("details").map_elements(extract_pnl, return_dtype=pl.Float64).alias("pnl")
            )
            
            good_process_bad_outcome = len(pq_logs.filter((pl.col("metric_value") >= 8) & (pl.col("pnl") < 0)))
            bad_process_good_outcome = len(pq_logs.filter((pl.col("metric_value") <= 4) & (pl.col("pnl") > 0)))
            
            variance_msg = (
                f"\nProcess vs Outcome Matrix:\n"
                f"- Good Process / Bad Outcome (Variance/Normal Loss): {good_process_bad_outcome}\n"
                f"- Bad Process / Good Outcome (Dumb Luck): {bad_process_good_outcome}\n"
            )
            
        report = f"--- Weekly Behavioral Report ---\nTotal logs: {len(df)}\n"
        
        counts = df.group_by("log_type").count().to_dicts()
        for c in counts:
            report += f"{c['log_type']}: {c['count']} events\n"
            
        report += variance_msg
        return report
