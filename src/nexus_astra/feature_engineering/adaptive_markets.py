"""Adaptive Markets Hypothesis engine based on Andrew Lo's theory."""

from __future__ import annotations

import logging
from datetime import date
from typing import Dict, Any, List

import numpy as np

from nexus_astra.data_ingestion.database import AdaptiveRegime, database_manager

logger = logging.getLogger(__name__)


class AdaptiveMarkets:
    """Manages strategy selection based on market efficiency (ER)."""

    def __init__(self) -> None:
        pass

    def calculate_efficiency_ratio(self, prices: np.ndarray | List[float], window: int = 20) -> float:
        """
        ER = |price_change_over_window| / sum(|daily_changes|).
        ER near 1 = efficient (trending). ER near 0 = inefficient (mean-reverting).
        """
        arr = np.asarray(prices, dtype=float)
        if len(arr) <= window:
            # Not enough data for full window
            if len(arr) < 2:
                return 0.5
            window = len(arr) - 1
            
        # Price change over window
        net_change = abs(arr[-1] - arr[-(window + 1)])
        
        # Sum of absolute daily changes
        daily_diffs = np.diff(arr[-(window + 1):])
        sum_abs_changes = np.sum(np.abs(daily_diffs))
        
        if sum_abs_changes == 0:
            return 0.0
            
        er = net_change / sum_abs_changes
        return float(np.clip(er, 0.0, 1.0))

    def regime_efficiency_map(self, er: float) -> str:
        """
        Identify which strategies work in which regimes:
        High ER (>0.6) -> momentum strategies
        Low ER (<0.3) -> mean reversion strategies
        """
        if er > 0.6:
            return "MOMENTUM"
        elif er < 0.3:
            return "MEAN_REVERSION"
        else:
            return "TRANSITION"

    def strategy_selector(self, er_series: np.ndarray | List[float], window: int = 20) -> Dict[str, Any]:
        """
        Based on ER dynamics, automatically select signal weights.
        """
        arr = np.asarray(er_series, dtype=float)
        if len(arr) < 11:
            return {"bias": "NEUTRAL", "size_multiplier": 1.0}
            
        current_er = arr[-1]
        past_er_5 = arr[-6] if len(arr) >= 6 else arr[0]
        
        # Count days under 0.2
        days_under_0_2 = 0
        for val in reversed(arr):
            if val < 0.2:
                days_under_0_2 += 1
            else:
                break
                
        bias = self.regime_efficiency_map(current_er)
        size_multiplier = 1.0
        
        if days_under_0_2 > 10:
            bias = "ADAPTING"
            size_multiplier = 0.50
            logger.warning("Market is ADAPTING to new regime (ER < 0.2 for >10 days). Reducing sizes 50%.")
            
        elif past_er_5 <= 0.3 and current_er >= 0.5:
            bias = "MOMENTUM_RISING"
            logger.info("ER rising from low to high. Increasing momentum signal weights.")
            
        elif past_er_5 >= 0.6 and current_er <= 0.4:
            bias = "MEAN_REV_RISING"
            logger.info("ER falling from high to low. Increasing mean reversion signal weights.")
            
        return {
            "bias": bias,
            "size_multiplier": size_multiplier
        }

    def inefficiency_window_detector(self, er_series: np.ndarray | List[float]) -> bool:
        """
        Flag when ER has been stable for >30 days then shifts >0.2 in <5 days.
        This is the 'adaptive moment' -> size up 25% for next 2 weeks.
        """
        arr = np.asarray(er_series, dtype=float)
        if len(arr) < 35:
            return False
            
        # Stable for 30 days prior to the last 5 days
        stable_window = arr[-35:-5]
        std_stable = np.std(stable_window)
        mean_stable = np.mean(stable_window)
        
        # Shift in last 5 days
        recent_shift = abs(arr[-1] - arr[-6])
        
        if std_stable < 0.1 and recent_shift > 0.2:
            logger.warning("ADAPTIVE MOMENT DETECTED! ER shifted > 0.2 rapidly after 30d stability. Size up 25%.")
            return True
            
        return False

    def process_daily(self, prices_series: np.ndarray | List[float]) -> Dict[str, Any]:
        """
        Update daily. Store in SQLite AdaptiveRegime.
        """
        # Calculate trailing ER series for the last ~40 days to run detectors
        prices = np.asarray(prices_series, dtype=float)
        if len(prices) < 40:
            logger.warning("Not enough price data for robust Adaptive Markets processing.")
            return {"status": "INSUFFICIENT_DATA"}
            
        er_series = []
        # Calculate rolling ER for the last 35 days (requires 20 days prior per point)
        # We need roughly 55 days of price history for 35 days of ER.
        # If we have less, we just calculate as many ER points as possible.
        max_er_points = len(prices) - 20
        for i in range(max_er_points):
            idx = i + 20
            window_prices = prices[i:idx+1]
            er_series.append(self.calculate_efficiency_ratio(window_prices))
            
        er_series = np.array(er_series)
        
        current_er = er_series[-1]
        er_ma = np.mean(er_series[-10:]) if len(er_series) >= 10 else current_er
        
        strategy_info = self.strategy_selector(er_series)
        is_inefficient = self.inefficiency_window_detector(er_series)
        
        final_multiplier = strategy_info["size_multiplier"]
        if is_inefficient:
            final_multiplier *= 1.25 # Size up 25%
            
        with database_manager.session_scope() as session:
            record = AdaptiveRegime(
                date=date.today(),
                er_value=current_er,
                er_moving_avg=er_ma,
                strategy_bias=strategy_info["bias"],
                size_multiplier=final_multiplier,
                inefficiency_flag=is_inefficient
            )
            session.add(record)
            
        return {
            "er": current_er,
            "bias": strategy_info["bias"],
            "multiplier": final_multiplier,
            "inefficiency_flag": is_inefficient
        }
