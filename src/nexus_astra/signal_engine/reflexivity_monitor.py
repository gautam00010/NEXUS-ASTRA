"""Reflexivity Engine based on Soros's theory of feedback loops."""

from __future__ import annotations

import logging
from datetime import date
from typing import Dict, Any, List, Tuple

import numpy as np

from nexus_astra.data_ingestion.database import ReflexivityState, database_manager

logger = logging.getLogger(__name__)


class ReflexivityEngine:
    """Calculates derivatives of market flows to identify accelerating or exhausting feedback loops."""

    def __init__(self) -> None:
        pass

    def calculate_second_derivative(self, series: np.ndarray | List[float]) -> Tuple[float, float, float]:
        """
        Calculates the latest value, first derivative (velocity), and second derivative (acceleration).
        Returns: (value, d1, d2)
        """
        arr = np.asarray(series, dtype=float)
        if len(arr) < 3:
            return (arr[-1] if len(arr) > 0 else 0.0, 0.0, 0.0)
            
        val = arr[-1]
        
        # d1 = current - previous
        d1 = arr[-1] - arr[-2]
        
        # d2 = current d1 - previous d1
        prev_d1 = arr[-2] - arr[-3]
        d2 = d1 - prev_d1
        
        return float(val), float(d1), float(d2)

    def feedback_loop_classification(self, d1: float, d2: float, threshold: float = 0.01) -> str:
        """
        Classify the state of the feedback loop.
        ACCELERATING: d1 and d2 same sign.
        EXHAUSTING: d1 and d2 opposite signs.
        STABLE: Both near zero.
        """
        if abs(d1) < threshold and abs(d2) < threshold:
            return "STABLE"
            
        if (d1 > 0 and d2 > 0) or (d1 < 0 and d2 < 0):
            return "ACCELERATING"
            
        if (d1 > 0 and d2 < 0) or (d1 < 0 and d2 > 0):
            return "EXHAUSTING"
            
        return "STABLE"

    def apply_to_fii(self, fii_series: np.ndarray | List[float]) -> Dict[str, Any]:
        """
        Track FII net flows. Classify current state.
        Only generate signal when state = EXHAUSTING.
        """
        val, d1, d2 = self.calculate_second_derivative(fii_series)
        # Using a higher threshold for FII flows which can be noisy (e.g. 50 Cr)
        state = self.feedback_loop_classification(d1, d2, threshold=50.0)
        
        signal = "NEUTRAL"
        if state == "EXHAUSTING":
            if d1 < 0 and d2 > 0:
                signal = "LONG" # Selling is decelerating
            elif d1 > 0 and d2 < 0:
                signal = "SHORT" # Buying is decelerating
                
        return {
            "metric": "FII_FLOW",
            "value": val,
            "d1": d1,
            "d2": d2,
            "state": state,
            "signal": signal
        }

    def apply_to_vix(self, vix_series: np.ndarray | List[float]) -> Dict[str, Any]:
        """
        Track India VIX. 
        VIX rising + d2 positive = panic accelerating (STAY_OUT).
        VIX rising + d2 negative = panic exhausting (BOTTOM_FORMING).
        """
        val, d1, d2 = self.calculate_second_derivative(vix_series)
        state = self.feedback_loop_classification(d1, d2, threshold=0.1)
        
        signal = "NEUTRAL"
        if d1 > 0:
            if d2 > 0:
                signal = "STAY_OUT" # Panic accelerating
            elif d2 < 0:
                signal = "BOTTOM_FORMING" # Panic exhausting
                
        return {
            "metric": "INDIA_VIX",
            "value": val,
            "d1": d1,
            "d2": d2,
            "state": state,
            "signal": signal
        }

    def reflexivity_score(self, fii_res: Dict[str, Any], vix_res: Dict[str, Any]) -> float:
        """
        Composite score -100 to +100.
        Positive = favors longs. Negative = favors shorts.
        """
        score = 0.0
        
        # FII Exhaustion logic
        if fii_res["signal"] == "LONG":
            score += 50.0
        elif fii_res["signal"] == "SHORT":
            score -= 50.0
        elif fii_res["state"] == "ACCELERATING":
            if fii_res["d1"] > 0:
                score += 30.0 # Accelerating buying
            else:
                score -= 30.0 # Accelerating selling
                
        # VIX logic
        if vix_res["signal"] == "BOTTOM_FORMING":
            score += 50.0
        elif vix_res["signal"] == "STAY_OUT":
            score -= 50.0 # Extreme panic
        elif vix_res["state"] == "EXHAUSTING" and vix_res["d1"] < 0:
            # VIX falling but decelerating
            score -= 20.0
            
        return float(np.clip(score, -100.0, 100.0))

    def update_daily(self, fii_series: np.ndarray | List[float], vix_series: np.ndarray | List[float]) -> float:
        """
        Calculate metrics, store in SQLite ReflexivityState, return composite score.
        """
        fii_res = self.apply_to_fii(fii_series)
        vix_res = self.apply_to_vix(vix_series)
        
        score = self.reflexivity_score(fii_res, vix_res)
        
        with database_manager.session_scope() as session:
            for res in [fii_res, vix_res]:
                record = ReflexivityState(
                    date=date.today(),
                    metric_name=res["metric"],
                    value=res["value"],
                    first_derivative=res["d1"],
                    second_derivative=res["d2"],
                    state=res["state"],
                    reflexivity_score=score
                )
                session.add(record)
                
        logger.info(f"Reflexivity Score updated: {score}. FII State: {fii_res['state']}, VIX State: {vix_res['state']}")
        return score
