"""INR Carry Regime engine based on global macro dollar liquidity (DXY, Fed Funds, US10Y)."""

from __future__ import annotations

import logging
from datetime import date
from typing import Dict, Any, List

from nexus_astra.data_ingestion.database import CarryRegime, database_manager

logger = logging.getLogger(__name__)


class INRCarryRegime:
    """Manages the highest-conviction macro overlay: The Global Carry Trade into India."""

    def __init__(self) -> None:
        pass

    def fed_cycle_classifier(self, fed_funds_6m: List[float]) -> str:
        """
        FED_CUTTING: Fed Funds rate declining over 6 months
        FED_HIKING: Fed Funds rate increasing
        FED_PAUSED: No change over 3 months
        """
        if len(fed_funds_6m) < 6:
            return "FED_PAUSED"
            
        current = fed_funds_6m[-1]
        six_mo_ago = fed_funds_6m[0]
        
        # Check last 3 months for pause
        recent_3m = fed_funds_6m[-3:]
        if all(r == current for r in recent_3m):
            return "FED_PAUSED"
            
        if current < six_mo_ago:
            return "FED_CUTTING"
        elif current > six_mo_ago:
            return "FED_HIKING"
            
        return "FED_PAUSED"

    def dxy_regime(self, current_dxy: float, dxy_50w_ma: float) -> str:
        """
        DXY below 50-week moving average = weakening dollar = carry trade attractive.
        """
        if current_dxy < dxy_50w_ma:
            return "WEAKENING"
        return "STRENGTHENING"

    def us10y_trend(self, us10y_3m: List[float]) -> str:
        """
        US 10Y yield declining over 3 months = global liquidity easing.
        """
        if len(us10y_3m) < 3:
            return "NEUTRAL"
            
        current = us10y_3m[-1]
        three_mo_ago = us10y_3m[0]
        
        if current < three_mo_ago:
            return "EASING"
        elif current > three_mo_ago:
            return "TIGHTENING"
            
        return "NEUTRAL"

    def carry_score(self, fed_state: str, dxy_state: str, us10y_state: str) -> float:
        """
        Composite 0-100. High carry regime = Fed cutting + DXY weakening + US10Y declining.
        """
        score = 0.0
        
        if fed_state == "FED_CUTTING":
            score += 40.0
        elif fed_state == "FED_PAUSED":
            score += 20.0
            
        if dxy_state == "WEAKENING":
            score += 30.0
            
        if us10y_state == "EASING":
            score += 30.0
            
        return min(score, 100.0)

    def signal_weight_boost(self, carry_score: float, base_signals: Dict[str, Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
        """
        When carry_score > 70:
        - All long Indian equities get +20% weight
        - FII flow signals get +30% weight
        - Short signals suppressed
        - Crypto unchanged
        """
        adjusted = {}
        for sig_id, sig_data in base_signals.items():
            # Deep copy simulation
            new_data = sig_data.copy()
            asset_class = new_data.get("asset_class", "EQUITY")
            direction = new_data.get("direction", "LONG")
            sig_type = new_data.get("type", "NORMAL")
            
            if carry_score > 70:
                if asset_class == "CRYPTO":
                    # Unchanged
                    pass
                elif direction == "SHORT":
                    new_data["weight"] = 0.0 # Suppress
                else:
                    # Longs
                    if sig_type == "FII_FLOW":
                        new_data["weight"] *= 1.30
                    else:
                        new_data["weight"] *= 1.20
                        
            adjusted[sig_id] = new_data
            
        return adjusted

    def carry_duration_estimate(self, fed_cycle: str, months_in_cycle: int) -> float:
        """
        Fed cutting cycles last 12-24 months. As approach end, gradually reduce boost.
        Returns a modifier from 0.0 to 1.0.
        """
        if fed_cycle != "FED_CUTTING":
            return 1.0
            
        # If in a cutting cycle, expect ~18 months average
        if months_in_cycle >= 18:
            return 0.25 # Severely taper
        elif months_in_cycle >= 12:
            return 0.50 # Begin tapering
        elif months_in_cycle >= 8:
            return 0.80
            
        return 1.0

    def process_weekly(
        self, 
        current_date: date,
        fed_funds_6m: List[float],
        current_dxy: float,
        dxy_50w_ma: float,
        us10y_3m: List[float],
        months_in_fed_cycle: int
    ) -> Dict[str, Any]:
        """
        Calculate carry states, store in SQLite.
        """
        fed_state = self.fed_cycle_classifier(fed_funds_6m)
        dxy_state = self.dxy_regime(current_dxy, dxy_50w_ma)
        us10y_state = self.us10y_trend(us10y_3m)
        
        score = self.carry_score(fed_state, dxy_state, us10y_state)
        duration_mod = self.carry_duration_estimate(fed_state, months_in_fed_cycle)
        
        # Apply duration tapering to the effective score internally or keep them separate
        # We'll just store the modifier separately so strategy engine can multiply boost by duration_mod.
        
        with database_manager.session_scope() as session:
            record = CarryRegime(
                date=current_date,
                fed_cycle=fed_state,
                dxy_regime=dxy_state,
                us10y_trend=us10y_state,
                carry_score=score,
                duration_modifier=duration_mod
            )
            session.add(record)
            
        return {
            "fed_state": fed_state,
            "dxy_state": dxy_state,
            "us10y_state": us10y_state,
            "carry_score": score,
            "duration_modifier": duration_mod
        }
