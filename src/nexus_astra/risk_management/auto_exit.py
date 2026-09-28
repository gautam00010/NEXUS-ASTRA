"""Auto-Exit Engine to ruthlessly cut losers and optimally scale winners."""

from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Dict, Any

from nexus_astra.data_ingestion.database import AutoExitPlan, PsychologyLog, database_manager
from nexus_astra.delivery.telegram_delivery import send_telegram_signal
import asyncio

logger = logging.getLogger(__name__)


class AutoExitEngine:
    """Pre-calculated mechanical exit rules targeting behavioral loss aversion."""

    def __init__(self) -> None:
        pass

    def generate_exit_plan(
        self, 
        signal_id: str, 
        symbol: str, 
        entry_price: float, 
        stop_loss_price: float, 
        expected_duration_days: int
    ) -> Dict[str, Any]:
        """
        Pre-calculate and lock in targets based on absolute risk.
        Target 1: 1.5x risk
        Target 2: 2.5x risk
        Target 3: 4.0x risk
        """
        risk = abs(entry_price - stop_loss_price)
        if risk == 0:
            risk = entry_price * 0.01 # Default to 1% risk if unspecified
            
        direction = 1 if stop_loss_price < entry_price else -1
        
        target_1 = entry_price + (direction * risk * 1.5)
        target_2 = entry_price + (direction * risk * 2.5)
        target_3 = entry_price + (direction * risk * 4.0)
        
        time_stop = date.today() + timedelta(days=expected_duration_days + 2)
        
        with database_manager.session_scope() as session:
            existing = session.query(AutoExitPlan).filter_by(signal_id=signal_id).first()
            if not existing:
                plan = AutoExitPlan(
                    signal_id=signal_id,
                    symbol=symbol,
                    entry_price=entry_price,
                    stop_loss=stop_loss_price,
                    target_1=target_1,
                    target_2=target_2,
                    target_3=target_3,
                    time_stop_date=time_stop,
                    status="ACTIVE"
                )
                session.add(plan)
                
        logger.info(f"Generated Auto-Exit Plan for {symbol} (Signal {signal_id}): SL={stop_loss_price}, T1={target_1}, T2={target_2}, T3={target_3}, TimeStop={time_stop}")
        return {
            "stop_loss": stop_loss_price,
            "target_1": target_1,
            "target_2": target_2,
            "target_3": target_3,
            "time_stop_date": time_stop
        }

    async def enforce_exit_rules(self, signal_id: str, current_price: float) -> bool:
        """
        Check daily at 3:25 PM IST.
        If any rule triggered, send MANDATORY_EXIT_ALERT to Telegram.
        Returns True if exit triggered.
        """
        with database_manager.session_scope() as session:
            plan = session.query(AutoExitPlan).filter_by(signal_id=signal_id, status="ACTIVE").first()
            
            if not plan:
                return False
                
            is_long = plan.target_1 > plan.entry_price
            exit_reason = None
            
            if is_long:
                if current_price <= plan.stop_loss:
                    exit_reason = f"STOP LOSS HIT at {plan.stop_loss}"
                elif current_price >= plan.target_3:
                    exit_reason = f"FINAL TARGET HIT at {plan.target_3}"
            else:
                if current_price >= plan.stop_loss:
                    exit_reason = f"STOP LOSS HIT at {plan.stop_loss}"
                elif current_price <= plan.target_3:
                    exit_reason = f"FINAL TARGET HIT at {plan.target_3}"
                    
            if not exit_reason and date.today() >= plan.time_stop_date:
                exit_reason = f"TIME STOP EXPIRED (Max hold till {plan.time_stop_date})"
                
            if exit_reason:
                msg = f"MANDATORY_EXIT_ALERT: {plan.symbol} | {exit_reason}. This is a pre-committed exit. Override requires written justification logged to PsychologyLog."
                logger.warning(msg)
                
                payload = {
                    "Type": "MANDATORY EXIT",
                    "Signal ID": signal_id,
                    "Symbol": plan.symbol,
                    "Reason": exit_reason,
                    "Action": "MARKET SELL IMMEDATELY"
                }
                try:
                    await send_telegram_signal(payload)
                except Exception as e:
                    logger.error(f"Failed to send exit alert: {e}")
                    
                plan.status = "EXITED"
                return True
                
        return False

    async def partial_profit_tracker(self, signal_id: str, current_price: float) -> str | None:
        """
        When Target 1 hit, automatically suggest moving stop to breakeven.
        When Target 2 hit, suggest trailing stop activation.
        """
        with database_manager.session_scope() as session:
            plan = session.query(AutoExitPlan).filter_by(signal_id=signal_id, status="ACTIVE").first()
            
            if not plan:
                return None
                
            is_long = plan.target_1 > plan.entry_price
            suggestion = None
            
            if is_long:
                if current_price >= plan.target_2:
                    suggestion = f"Target 2 hit ({plan.target_2}). Activate trailing stop. Book 30%."
                elif current_price >= plan.target_1:
                    suggestion = f"Target 1 hit ({plan.target_1}). Move SL to breakeven ({plan.entry_price}). Book 50%."
            else:
                if current_price <= plan.target_2:
                    suggestion = f"Target 2 hit ({plan.target_2}). Activate trailing stop. Book 30%."
                elif current_price <= plan.target_1:
                    suggestion = f"Target 1 hit ({plan.target_1}). Move SL to breakeven ({plan.entry_price}). Book 50%."
                    
            if suggestion:
                logger.info(f"PARTIAL PROFIT: {plan.symbol} | {suggestion}")
                payload = {
                    "Type": "PROFIT TRACKER",
                    "Signal ID": signal_id,
                    "Symbol": plan.symbol,
                    "Action": suggestion
                }
                try:
                    await send_telegram_signal(payload)
                except Exception:
                    pass
                return suggestion
                
        return None

    def no_manual_override_flag(self, signal_id: str, two_factor_msg: str, reason: str) -> bool:
        """
        If trader attempts to cancel exit within 24h of trigger, require 2-factor confirmation:
        type 'I OVERRIDE SYSTEM' + provide reason.
        Log to PsychologyLog with timestamp.
        """
        if two_factor_msg.strip().upper() != "I OVERRIDE SYSTEM":
            logger.error("Override failed: Incorrect 2FA confirmation string.")
            return False
            
        if not reason or len(reason.strip()) < 10:
            logger.error("Override failed: Must provide a detailed reason.")
            return False
            
        with database_manager.session_scope() as session:
            session.add(PsychologyLog(
                date=date.today(),
                log_type="MANUAL_OVERRIDE",
                signal_id=signal_id,
                details=f"OVERRIDE EXECUTED. Reason: {reason}"
            ))
            
            plan = session.query(AutoExitPlan).filter_by(signal_id=signal_id).first()
            if plan:
                plan.status = "OVERRIDDEN"
                
        logger.warning(f"SYSTEM OVERRIDDEN for signal {signal_id}. Behavioral violation logged.")
        return True
