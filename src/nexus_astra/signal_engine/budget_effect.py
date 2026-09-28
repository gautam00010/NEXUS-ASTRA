"""Union Budget and RBI Policy event alpha engine."""

from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Dict, Any, List

from nexus_astra.data_ingestion.database import EventCalendar, database_manager

logger = logging.getLogger(__name__)


class BudgetEffect:
    """Manages structural pre-positioning and aftermath capture for macro events (Budget, RBI)."""

    def __init__(self) -> None:
        pass

    def budget_proximity_flag(self, current_date: date, budget_date: date = None) -> str:
        """
        Flag the active structural window around the Union Budget.
        Default assumption: Feb 1.
        """
        if budget_date is None:
            budget_date = date(current_date.year, 2, 1)
            
        days_to_budget = (budget_date - current_date).days
        
        if 8 <= days_to_budget <= 22: # Approx Jan 10 - Jan 24
            return "BUDGET_RUNUP_START"
        elif 1 <= days_to_budget <= 7: # Approx Jan 25 - Jan 30
            return "BUDGET_RUNUP_INTENSE"
        elif days_to_budget == 1: # Jan 31
            return "BUDGET_EVE"
        elif days_to_budget == 0:
            return "BUDGET_DAY"
        elif -6 <= days_to_budget <= -1: # Feb 2 - Feb 7
            return "BUDGET_AFTERMATH"
            
        return "NO_BUDGET_EVENT"

    def sector_rotation_rules(self, proximity_flag: str, budget_outcome: str = None) -> Dict[str, Any]:
        """
        Sector shifts based on the proximity window.
        """
        rules = {"action": "NEUTRAL", "overweight": [], "underweight": [], "cash_mode": False}
        
        if proximity_flag in ["BUDGET_RUNUP_START", "BUDGET_RUNUP_INTENSE"]:
            rules["overweight"] = ["INFRASTRUCTURE", "DEFENSE", "CAPITAL_GOODS"]
            rules["underweight"] = ["IT", "FMCG"]
            
        elif proximity_flag == "BUDGET_EVE":
            # Just before the event, risk mitigation
            rules["action"] = "HEDGE_PORTFOLIO"
            
        elif proximity_flag == "BUDGET_AFTERMATH" and budget_outcome:
            if budget_outcome == "NO_SURPRISE":
                rules["action"] = "LONG_INDEX_VOL_CRUSH"
            elif budget_outcome == "NEGATIVE_SURPRISE":
                rules["action"] = "LIQUIDATE_TO_CASH"
                rules["cash_mode"] = True
                
        return rules

    def historical_pattern_matcher(self, current_sector_perf: str, historical_patterns: Dict[str, str]) -> Dict[str, float]:
        """
        Compare current pre-budget sector performance to historical patterns (2015-2024).
        If matched to 'infrastructure bid', increase infra weights heavily.
        """
        # Simulated matching logic
        modifiers = {"INFRASTRUCTURE": 1.0, "DEFENSE": 1.0, "IT": 1.0}
        
        matched_pattern = historical_patterns.get(current_sector_perf)
        if matched_pattern == "INFRASTRUCTURE_BID":
            logger.info("Historical match found: Infrastructure Bid. Increasing infra weights 25%.")
            modifiers["INFRASTRUCTURE"] = 1.25
            
        return modifiers

    def rbi_policy_overlay(self, current_date: date, rbi_dates: List[date], outcome: str = None) -> str:
        """
        RBI policy dates (typically every 2 months).
        3 days before = no new positions.
        Day after 'no surprise' = vol crush capture.
        """
        for rbi_date in rbi_dates:
            days_diff = (rbi_date - current_date).days
            
            if 0 < days_diff <= 3:
                return "NO_NEW_POSITIONS"
            elif days_diff == 0:
                return "POLICY_DAY"
            elif days_diff == -1 and outcome == "NO_SURPRISE":
                return "VOL_CRUSH_CAPTURE"
                
        return "NEUTRAL"

    def process_daily(
        self, 
        current_date: date, 
        budget_date: date, 
        budget_outcome: str, 
        rbi_dates: List[date], 
        rbi_outcome: str,
        current_sector_perf: str,
        historical_patterns: Dict[str, str]
    ) -> Dict[str, Any]:
        """
        Orchestrator for budget and RBI events. Store in SQLite.
        """
        budget_flag = self.budget_proximity_flag(current_date, budget_date)
        sector_rules = self.sector_rotation_rules(budget_flag, budget_outcome)
        
        historical_match_flag = False
        if budget_flag in ["BUDGET_RUNUP_START", "BUDGET_RUNUP_INTENSE"]:
            pattern_mods = self.historical_pattern_matcher(current_sector_perf, historical_patterns)
            if pattern_mods.get("INFRASTRUCTURE", 1.0) > 1.0:
                historical_match_flag = True
                
        rbi_flag = self.rbi_policy_overlay(current_date, rbi_dates, rbi_outcome)
        
        with database_manager.session_scope() as session:
            # Log Budget State
            if budget_flag != "NO_BUDGET_EVENT":
                b_record = EventCalendar(
                    date=current_date,
                    event_type="BUDGET",
                    proximity_flag=budget_flag,
                    sector_rotation_bias=str(sector_rules["overweight"]),
                    historical_match_flag=historical_match_flag
                )
                session.add(b_record)
                
            # Log RBI State
            if rbi_flag != "NEUTRAL":
                r_record = EventCalendar(
                    date=current_date,
                    event_type="RBI_POLICY",
                    proximity_flag=rbi_flag,
                    sector_rotation_bias=None,
                    historical_match_flag=False
                )
                session.add(r_record)
                
        return {
            "budget_flag": budget_flag,
            "sector_rules": sector_rules,
            "historical_match_flag": historical_match_flag,
            "rbi_flag": rbi_flag
        }
