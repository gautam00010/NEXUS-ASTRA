"""Calendar Alpha Engine to detect SIP structural bids."""

from __future__ import annotations

import logging
import calendar
from datetime import date
from typing import Dict, Any

from nexus_astra.data_ingestion.database import CalendarAlpha, database_manager

logger = logging.getLogger(__name__)


class SIPFloorDetector:
    """Detects and integrates structural SIP flows into signal weighting."""

    def __init__(self) -> None:
        pass

    def sip_inflow_estimate(self, current_flow_cr: float) -> float:
        """
        Track monthly SIP inflows. Current ~15,000-18,000 Cr/month.
        Returns the recorded flow.
        """
        return current_flow_cr

    def deployment_window_detector(self, current_date: date) -> Dict[str, bool]:
        """
        Fund managers deploy SIP inflows in first week (new subscriptions) 
        and last week (SIP debits hit).
        """
        day = current_date.day
        
        # Get last day of the current month
        _, last_day = calendar.monthrange(current_date.year, current_date.month)
        
        is_week_1 = day <= 7
        is_week_4 = (last_day - day) < 7
        
        return {
            "SIP_BID_WEEK_1": is_week_1,
            "SIP_BID_WEEK_4": is_week_4,
            "is_bid_week": is_week_1 or is_week_4
        }

    def sector_beneficiaries(self, is_bid_week: bool) -> Dict[str, bool]:
        """
        SIP flows disproportionately hit mid-cap and small-cap funds (less liquid).
        """
        return {
            "MIDCAP_SIP_BOOST": is_bid_week,
            "SMALLCAP_SIP_BOOST": is_bid_week
        }

    def signal_integration(self, is_bid_week: bool, base_weights: Dict[str, float]) -> Dict[str, float]:
        """
        During SIP bid weeks, increase weight of mid/small cap signals by 15%.
        Reduce large-cap signal weights by 10% (they're less affected).
        """
        adjusted = base_weights.copy()
        
        if is_bid_week:
            if "midcap" in adjusted:
                adjusted["midcap"] *= 1.15
            if "smallcap" in adjusted:
                adjusted["smallcap"] *= 1.15
            if "largecap" in adjusted:
                adjusted["largecap"] *= 0.90
                
        return adjusted

    def monthly_flow_tracker(self, current_month_flow: float, last_month_flow: float) -> bool:
        """
        If monthly SIP inflow drops >20% MoM -> structural bid weakening.
        """
        if last_month_flow <= 0:
            return False
            
        drop_pct = (last_month_flow - current_month_flow) / last_month_flow
        
        if drop_pct > 0.20:
            logger.warning("SIP_SLOWDOWN_Caution: Monthly SIP inflow dropped >20% MoM. Structural bid weakening!")
            return True
            
        return False

    def process_daily(self, current_date: date, current_flow: float, last_month_flow: float, base_weights: Dict[str, float]) -> Dict[str, Any]:
        """
        Process all rules and update DB.
        """
        window = self.deployment_window_detector(current_date)
        is_bid = window["is_bid_week"]
        
        beneficiaries = self.sector_beneficiaries(is_bid)
        adjusted_weights = self.signal_integration(is_bid, base_weights)
        slowdown = self.monthly_flow_tracker(current_flow, last_month_flow)
        
        with database_manager.session_scope() as session:
            record = CalendarAlpha(
                date=current_date,
                sip_inflow_cr=current_flow,
                is_bid_week_1=window["SIP_BID_WEEK_1"],
                is_bid_week_4=window["SIP_BID_WEEK_4"],
                midcap_boost=beneficiaries["MIDCAP_SIP_BOOST"],
                smallcap_boost=beneficiaries["SMALLCAP_SIP_BOOST"],
                slowdown_caution=slowdown
            )
            session.add(record)
            
        return {
            "window": window,
            "beneficiaries": beneficiaries,
            "slowdown": slowdown,
            "adjusted_weights": adjusted_weights
        }
