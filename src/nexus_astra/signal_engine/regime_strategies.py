"""Regime Conditional Engine to dynamically shift strategy weights based on market state."""

from __future__ import annotations

import logging
from datetime import date
from typing import Dict, Any, List

import numpy as np

from nexus_astra.data_ingestion.database import RegimeStrategies, database_manager

logger = logging.getLogger(__name__)


class RegimeConditionalEngine:
    """Classifies market regime and assigns strategy weights accordingly."""

    def __init__(self) -> None:
        pass

    def regime_classifier(self, vix: float, price: float, ema_200: float, fii_net_20d: float) -> str:
        """
        Classify current regime.
        VIX: <15 (calm), 15-22 (normal), >22 (stress), >30 (crisis)
        Trend: Price > 200 EMA (bull), < 200 EMA (bear)
        FII flow: Net positive (inflow), negative (outflow)
        """
        # VIX Classification
        if vix > 30:
            v_state = "Crisis"
        elif vix > 22:
            v_state = "Stress"
        elif vix >= 15:
            v_state = "Normal"
        else:
            v_state = "Calm"
            
        # Trend Classification
        t_state = "Bull" if price > ema_200 else "Bear"
        
        # FII Classification
        f_state = "Inflow" if fii_net_20d > 0 else "Outflow"
        
        return f"{t_state}-{v_state}-{f_state}"

    def regime_persistence_check(self, current_raw_regime: str, regime_history: List[str]) -> str:
        """
        Require regime to persist for 3+ days before switching strategies to prevent whipsaw.
        If history is less than 3 days, default to the oldest known regime or current if none.
        """
        if not regime_history:
            return current_raw_regime
            
        # Check last 2 days + current (3 days total)
        recent_history = regime_history[-2:]
        all_same = all(r == current_raw_regime for r in recent_history)
        
        if all_same and len(recent_history) == 2:
            return current_raw_regime
            
        # Otherwise, fall back to the previously established persistent regime
        return regime_history[-1]

    def strategy_per_regime(self, regime_string: str) -> Dict[str, float]:
        """
        For each regime combination, load pre-calibrated signal weights.
        """
        # Default safety
        weights = {"momentum": 0.0, "mean_reversion": 0.0, "contrarian": 0.0, "cash": 1.0}
        
        if "Crisis" in regime_string:
            # Crisis: 100% Cash
            return weights
            
        if "Bull-Calm" in regime_string:
            weights = {"momentum": 0.60, "mean_reversion": 0.20, "contrarian": 0.20, "cash": 0.0}
        elif "Bear-Stress" in regime_string:
            weights = {"momentum": 0.20, "mean_reversion": 0.30, "contrarian": 0.50, "cash": 0.0}
        elif "Bull-Stress" in regime_string:
            weights = {"momentum": 0.30, "mean_reversion": 0.40, "contrarian": 0.30, "cash": 0.0}
        elif "Bear-Calm" in regime_string:
            weights = {"momentum": 0.40, "mean_reversion": 0.40, "contrarian": 0.20, "cash": 0.0}
        elif "Normal" in regime_string:
            weights = {"momentum": 0.40, "mean_reversion": 0.40, "contrarian": 0.20, "cash": 0.0}
        else:
            # Fallback for undefined explicit combinations
            weights = {"momentum": 0.33, "mean_reversion": 0.33, "contrarian": 0.34, "cash": 0.0}
            
        return weights

    def regime_transition_boost(self, current_regime: str, previous_regime: str, days_since_transition: int) -> float:
        """
        When regime changes, increase position size 25% for 5 days. (Adaptive moment).
        Returns size multiplier (1.25 or 1.0).
        """
        if current_regime != previous_regime:
            return 1.25 # Day 1 of transition
            
        if days_since_transition < 5:
            return 1.25
            
        return 1.0

    def process_daily(
        self, 
        vix: float, 
        price: float, 
        ema_200: float, 
        fii_net_20d: float, 
        regime_history: List[str], 
        days_since_transition: int
    ) -> Dict[str, Any]:
        """
        Main orchestrator to classify, verify persistence, pull weights, and detect transitions.
        """
        raw_regime = self.regime_classifier(vix, price, ema_200, fii_net_20d)
        
        # Apply persistence filter
        confirmed_regime = self.regime_persistence_check(raw_regime, regime_history)
        
        previous_confirmed = regime_history[-1] if regime_history else confirmed_regime
        
        if confirmed_regime != previous_confirmed:
            days_since_transition = 0
            logger.warning(f"REGIME SHIFT CONFIRMED: {previous_confirmed} -> {confirmed_regime}")
        else:
            days_since_transition += 1
            
        weights = self.strategy_per_regime(confirmed_regime)
        multiplier = self.regime_transition_boost(confirmed_regime, previous_confirmed, days_since_transition)
        
        # Store in DB
        with database_manager.session_scope() as session:
            record = RegimeStrategies(
                date=date.today(),
                regime_name=confirmed_regime,
                momentum_weight=weights["momentum"],
                mean_reversion_weight=weights["mean_reversion"],
                contrarian_weight=weights["contrarian"],
                cash_weight=weights["cash"],
                size_multiplier=multiplier
            )
            session.add(record)
            
        return {
            "raw_regime": raw_regime,
            "confirmed_regime": confirmed_regime,
            "weights": weights,
            "multiplier": multiplier,
            "days_since_transition": days_since_transition
        }
