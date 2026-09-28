import logging
import time
from datetime import datetime, timedelta
from typing import Callable, Any, Optional
import smtplib
from email.mime.text import MIMEText
import os
from sqlalchemy import select, func, and_

from nexus_astra.data_ingestion.database import database_manager, SystemLogs, TheoreticalTrades, ActualFills, AdherenceDaily
from nexus_astra.monitoring.health_monitor import SystemHealth

logger = logging.getLogger(__name__)


class CircuitBreaker:
    """Self-healing and error recovery component."""

    def __init__(self):
        self.api_failures: dict[str, list[datetime]] = {}
        self.health_monitor = SystemHealth()
        
        # In-memory kill switch flag
        self.system_halted = False

    def log_event(self, component: str, level: str, message: str, details_json: Optional[str] = None) -> None:
        """Persists log to SQLite SystemLogs."""
        try:
            with database_manager.session_scope() as session:
                log = SystemLogs(
                    timestamp=datetime.now(),
                    component=component,
                    level=level,
                    message=message,
                    details_json=details_json
                )
                session.add(log)
        except Exception as e:
            logger.error(f"Failed to write to SystemLogs: {e}")

    def execute_api_call(self, api_name: str, primary_func: Callable, fallback_func: Optional[Callable] = None) -> Any:
        """Executes an API call with 3 fails / 10 mins fallback logic."""
        now = datetime.now()
        
        # Cleanup old failures
        if api_name in self.api_failures:
            self.api_failures[api_name] = [t for t in self.api_failures[api_name] if now - t < timedelta(minutes=10)]
            
        # Check if circuit is open
        if api_name in self.api_failures and len(self.api_failures[api_name]) >= 3:
            logger.warning(f"Circuit Breaker OPEN for {api_name}. Attempting fallback.")
            self.log_event(api_name, "WARNING", f"Circuit Breaker OPEN. 3 failures in 10 mins.")
            if fallback_func:
                return fallback_func()
            else:
                raise Exception(f"API {api_name} failed and no fallback provided.")

        try:
            result = primary_func()
            return result
        except Exception as e:
            logger.error(f"API Call Failed ({api_name}): {e}")
            self.health_monitor.track_api_error(api_name)
            
            if api_name not in self.api_failures:
                self.api_failures[api_name] = []
            self.api_failures[api_name].append(now)
            
            # Recurse to potentially trigger fallback if this was the 3rd fail
            return self.execute_api_call(api_name, primary_func, fallback_func)

    def execute_model(self, model_func: Callable, rule_based_fallback: Callable) -> Any:
        """Executes a predictive model, falling back to rule-based signals on exception."""
        try:
            return model_func()
        except Exception as e:
            logger.error(f"Model Execution Failed: {e}")
            self.log_event("ModelEnsemble", "ERROR", f"Model Execution Exception: {str(e)}")
            logger.info("Falling back to rule-based signals.")
            return rule_based_fallback()

    def check_data_staleness(self, latest_timestamp: datetime) -> bool:
        """Checks if data is >12 hours old. Returns False if stale."""
        now = datetime.now()
        if now - latest_timestamp > timedelta(hours=12):
            msg = "Data is STALE (>12 hours old). Pausing execution."
            logger.critical(msg)
            self.log_event("DataFreshness", "CRITICAL", msg)
            return False
        return True

    def send_alert(self, message: str, telegram_func: Callable) -> None:
        """Sends an alert via Telegram, falling back to SMTP email with exp backoff."""
        max_retries = 3
        delay = 1
        
        for attempt in range(max_retries):
            try:
                telegram_func(message)
                return
            except Exception as e:
                logger.warning(f"Telegram failed (Attempt {attempt+1}): {e}")
                time.sleep(delay)
                delay *= 2
                
        # Fallback to SMTP
        logger.error("Telegram completely failed. Falling back to SMTP Email.")
        self._send_smtp_email("NEXUS-ASTRA CRITICAL ALERT", message)

    def _send_smtp_email(self, subject: str, body: str) -> None:
        """Fallback email sender."""
        smtp_user = os.getenv("SMTP_USER")
        smtp_pass = os.getenv("SMTP_PASS")
        smtp_host = os.getenv("SMTP_HOST", "smtp.gmail.com")
        to_email = os.getenv("ALERT_EMAIL")
        
        if not all([smtp_user, smtp_pass, to_email]):
            logger.error("SMTP credentials missing. Cannot send fallback email.")
            return
            
        try:
            msg = MIMEText(body)
            msg['Subject'] = subject
            msg['From'] = smtp_user
            msg['To'] = to_email
            
            with smtplib.SMTP_SSL(smtp_host, 465) as server:
                server.login(smtp_user, smtp_pass)
                server.send_message(msg)
                logger.info("Fallback email sent successfully.")
        except Exception as e:
            logger.error(f"SMTP Fallback completely failed: {e}")

    def evaluate_kill_switch(self) -> bool:
        """
        Hard kill switch: if DD>15%, adherence<50%, or slippage>50 bps -> kill and send alert.
        Returns True if system should be HALTED.
        """
        if self.system_halted:
            return True
            
        with database_manager.session_scope() as session:
            triggered = False
            reasons = []

            # 1. DD & Adherence calculation from daily adherence tracking
            stmt = select(AdherenceDaily).order_by(AdherenceDaily.date)
            records = session.execute(stmt).scalars().all()
            
            if not records:
                # AdherenceDaily empty on day 1 of paper trading – do NOT trip kill switch
                logger.warning("KillSwitch: AdherenceDaily empty – skipping DD/adherence check (day 1 bootstrap)")
            else:
                cum_pnl = []
                current = 0.0
                total_theo = 0.0
                total_actual = 0.0
                
                for r in records:
                    current += float(r.actual_pnl)
                    cum_pnl.append(current)
                    total_theo += float(r.theoretical_pnl)
                    total_actual += float(r.actual_pnl)
                    
                peak = max(cum_pnl) if cum_pnl else 0.0
                current_equity = cum_pnl[-1] if cum_pnl else 0.0
                
                # Drawdown relative to 1M notional
                drawdown = (peak - current_equity) / 1_000_000.0
                adherence = total_actual / total_theo if total_theo != 0 else 1.0
                
                if drawdown > 0.15:
                    triggered = True
                    reasons.append(f"Drawdown {drawdown:.2%} > 15%")
                if total_theo != 0 and adherence < 0.50:
                    triggered = True
                    reasons.append(f"Adherence {adherence:.2%} < 50%")

            # 2. Slippage check – only if fills exist
            fills_stmt = select(ActualFills).order_by(ActualFills.actual_time.desc()).limit(20)
            recent_fills = session.execute(fills_stmt).scalars().all()
            if recent_fills:
                max_slip = max(float(f.slippage_actual) for f in recent_fills)
                if max_slip > 0.0050:
                    triggered = True
                    reasons.append(f"Excessive Slippage {max_slip * 10000.0:.1f} bps > 50 bps")

            if triggered:
                self.system_halted = True
                msg = f"KILL SWITCH ENGAGED: " + " | ".join(reasons)
                logger.critical(msg)
                self.log_event("KillSwitch", "CRITICAL", msg)
                self.send_alert(msg, lambda m: None)
                return True
                
        return False
