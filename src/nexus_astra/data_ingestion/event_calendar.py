import logging
from datetime import date, timedelta, datetime
import json
from typing import Dict, Any, List

from nexus_astra.data_ingestion.database import database_manager, EventRiskLog

logger = logging.getLogger(__name__)

class EventRisk:
    """Monitors upcoming corporate and macro events to assign risk scores and trading restrictions."""
    
    def __init__(self):
        # In a fully operational system, these would be populated from a calendar API or scraped from NSE
        self.rbi_policy_dates = [date(2026, 8, 6), date(2026, 10, 8)]
        self.union_budget_dates = [date(2026, 2, 1), date(2027, 2, 1)]
        self.msci_rebalance_dates = [date(2026, 5, 30), date(2026, 8, 30), date(2026, 11, 30)]
        
        # Simple mock of earnings dates for top symbols
        self.earnings_calendar = {
            "RELIANCE.NS": date.today() + timedelta(days=2),
            "TCS.NS": date.today() + timedelta(days=1),
            "HDFCBANK.NS": date.today() + timedelta(days=5),
            "INFY.NS": date.today() + timedelta(days=10)
        }

    def _is_quadruple_witching(self, check_date: date) -> bool:
        """Approximation: 3rd Friday of March, June, September, December."""
        if check_date.month in [3, 6, 9, 12]:
            if check_date.weekday() == 4: # Friday
                # Check if it's the 3rd Friday
                first_day = check_date.replace(day=1)
                first_friday = first_day + timedelta(days=(4 - first_day.weekday()) % 7)
                third_friday = first_friday + timedelta(days=14)
                return check_date == third_friday
        return False

    def assess_macro_events(self) -> List[Dict[str, Any]]:
        """Assess global/macro events that affect the whole market."""
        today = date.today()
        events = []
        
        # Check RBI Policy
        for d in self.rbi_policy_dates:
            if 0 <= (d - today).days <= 7:
                events.append({
                    "symbol": "MARKET",
                    "event_name": "RBI_POLICY_WEEK",
                    "risk_score": 80.0,
                    "trading_restriction": "NO_NEW_DIRECTIONAL"
                })
                
        # Check Union Budget
        for d in self.union_budget_dates:
            if 0 <= (d - today).days <= 2:
                events.append({
                    "symbol": "MARKET",
                    "event_name": "UNION_BUDGET_DAY",
                    "risk_score": 100.0,
                    "trading_restriction": "CASH_ONLY"
                })
                
        # Check MSCI Rebalance
        for d in self.msci_rebalance_dates:
            if 0 <= (d - today).days <= 5:
                events.append({
                    "symbol": "MARKET",
                    "event_name": "MSCI_REBALANCE",
                    "risk_score": 60.0,
                    "trading_restriction": "FRONT_RUN_ALLOWED"
                })
                
        # Check Quadruple Witching
        if self._is_quadruple_witching(today) or self._is_quadruple_witching(today + timedelta(days=1)):
            events.append({
                "symbol": "MARKET",
                "event_name": "QUADRUPLE_WITCHING",
                "risk_score": 75.0,
                "trading_restriction": "REDUCE_SIZE_50_PCT"
            })
            
        return events

    def assess_corporate_events(self, symbols: List[str]) -> List[Dict[str, Any]]:
        """Assess stock-specific events like earnings."""
        today = date.today()
        events = []
        
        for symbol in symbols:
            earnings_date = self.earnings_calendar.get(symbol)
            if earnings_date:
                days_to_earnings = (earnings_date - today).days
                if 0 <= days_to_earnings <= 3:
                    events.append({
                        "symbol": symbol,
                        "event_name": "EARNINGS_IN_3_DAYS",
                        "risk_score": 90.0,
                        "trading_restriction": "REDUCE_SIZE_50_PCT"
                    })
        return events

    def run_daily_assessment(self, symbols: List[str]) -> Dict[str, Any]:
        """Runs full event risk assessment and stores to DB."""
        macro_events = self.assess_macro_events()
        corp_events = self.assess_corporate_events(symbols)
        
        all_events = macro_events + corp_events
        
        with database_manager.session_scope() as session:
            for ev in all_events:
                # Check for existing record to avoid UniqueConstraint failure
                existing = session.query(EventRiskLog).filter_by(
                    symbol=ev["symbol"],
                    date=date.today(),
                    event_name=ev["event_name"]
                ).first()
                
                if not existing:
                    log = EventRiskLog(
                        symbol=ev["symbol"],
                        date=date.today(),
                        event_name=ev["event_name"],
                        risk_score=ev["risk_score"],
                        trading_restriction=ev["trading_restriction"]
                    )
                    session.add(log)
                
        logger.info(f"Event Risk Assessment complete. Logged {len(all_events)} events.")
        
        return {
            "total_events": len(all_events),
            "macro_restrictions": [ev["trading_restriction"] for ev in macro_events],
            "affected_symbols": [ev["symbol"] for ev in corp_events]
        }
