"""MSCI Rebalance Tracker for passive flow frontrunning."""

from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Dict, Any, List, Optional

from nexus_astra.data_ingestion.database import MSCICalendar, database_manager

logger = logging.getLogger(__name__)


class MSCIRebalance:
    """Tracks index inclusion/exclusion announcements and generates passive frontrunning signals."""

    def __init__(self) -> None:
        pass

    def load_rebalance_calendar(self) -> Dict[str, List[int]]:
        """
        Hard-code known rebalancing review months.
        Effective dates are usually mid-month.
        """
        return {
            "MSCI": [2, 5, 8, 11], # Feb, May, Aug, Nov
            "FTSE": [3, 6, 9, 12]  # Mar, Jun, Sep, Dec
        }

    def announcement_monitor(self, simulated_events: List[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        """
        Scrape MSCI announcement page (or use free data provider).
        Track: additions, deletions, weight increases, weight decreases for India.
        For this implementation, accepts a mock list of events.
        """
        if simulated_events is None:
            return []
        return simulated_events

    def frontrunning_window(self, current_date: date, event: Dict[str, Any]) -> str:
        """
        From announcement date to effective date (typically 3-4 weeks), flag the appropriate signal.
        """
        ann_date = event["announcement_date"]
        eff_date = event["effective_date"]
        action = event["action_type"]
        
        # Hard exit on effective date +/- 1 day
        days_to_effective = (eff_date - current_date).days
        
        if current_date < ann_date:
            return "NO_SIGNAL"
            
        if days_to_effective < -1:
            return "EXPIRED"
            
        if abs(days_to_effective) <= 1:
            return "HARD_EXIT"
            
        # Inside the active frontrunning window
        if action == "ADDITION":
            return "MSCI_ADDITION_BUY"
        elif action == "WEIGHT_INCREASE":
            return "MSCI_WEIGHT_INCREASE_BUY"
        elif action == "DELETION":
            return "MSCI_DELETION_SELL"
        elif action == "WEIGHT_DECREASE":
            return "MSCI_WEIGHT_DECREASE_SELL"
            
        return "NO_SIGNAL"

    def position_sizing(self, signal: str) -> float:
        """
        Size to 8-12% of portfolio for MSCI signals (high conviction, time-bound, structural).
        """
        if signal in ["MSCI_ADDITION_BUY", "MSCI_DELETION_SELL"]:
            return 0.12 # Full conviction for outright add/delete
        elif signal in ["MSCI_WEIGHT_INCREASE_BUY", "MSCI_WEIGHT_DECREASE_SELL"]:
            return 0.08 # Lower for weight adjustments
        else:
            return 0.0

    def historical_performance_tracker(self, historical_win_rates: List[float]) -> bool:
        """
        Track past MSCI signals. If win rate < 60% over last 4 rebalances, flag MSCI_EDGE_DECAYING.
        """
        if len(historical_win_rates) < 4:
            return False
            
        recent_4 = historical_win_rates[-4:]
        avg_win_rate = sum(recent_4) / 4.0
        
        if avg_win_rate < 0.60:
            logger.warning(f"MSCI_EDGE_DECAYING: Recent win rate is {avg_win_rate*100:.1f}% (< 60%).")
            return True
            
        return False

    def process_events(self, current_date: date, events: List[Dict[str, Any]], historical_win_rates: List[float] = None) -> List[Dict[str, Any]]:
        """
        Process the daily window for known active events. Store in SQLite MSCICalendar.
        """
        if historical_win_rates is None:
            historical_win_rates = [0.70, 0.65, 0.80, 0.75] # Default healthy edge
            
        edge_decaying = self.historical_performance_tracker(historical_win_rates)
        active_signals = []
        
        for event in events:
            signal = self.frontrunning_window(current_date, event)
            size = self.position_sizing(signal)
            
            # If edge is decaying, reduce position size mechanically by 50%
            if edge_decaying and size > 0:
                size *= 0.50
                
            active_signals.append({
                "symbol": event["symbol"],
                "action": event["action_type"],
                "signal": signal,
                "size": size,
                "edge_decaying": edge_decaying
            })
            
            with database_manager.session_scope() as session:
                record = MSCICalendar(
                    date=current_date,
                    announcement_date=event["announcement_date"],
                    effective_date=event["effective_date"],
                    symbol=event["symbol"],
                    action_type=event["action_type"],
                    target_weight=size,
                    trade_signal=signal,
                    performance_result=event.get("performance_result"),
                    edge_decaying=edge_decaying
                )
                session.add(record)
                
        return active_signals
