"""Risk Parity Sizer to allocate capital based on volatility inverse."""

from __future__ import annotations

import logging
from datetime import date
from typing import Dict, Any, List

import numpy as np
import polars as pl
from scipy import stats

from nexus_astra.data_ingestion.database import RiskParityAllocations, database_manager

logger = logging.getLogger(__name__)


class RiskParitySizer:
    """Calculates risk parity weights, leverages to hit target volatility, and adjusts for correlation."""

    def __init__(self) -> None:
        pass

    def calculate_asset_volatility(self, returns: np.ndarray | List[float], window: int = 20) -> float:
        """
        Annualized realized volatility from daily returns.
        """
        arr = np.asarray(returns, dtype=float)
        if len(arr) < 2:
            return 0.01
            
        recent = arr[-window:] if len(arr) >= window else arr
        daily_vol = float(np.std(recent, ddof=1))
        
        # Annualize
        return daily_vol * np.sqrt(252)

    def risk_budget_allocation(self, volatilities: Dict[str, float]) -> Dict[str, float]:
        """
        Allocate capital inversely proportional to volatility.
        w_i = (1/vol_i) / sum(1/vol_j)
        This makes each asset contribute equally to portfolio volatility (assuming 0 correlation).
        """
        inv_vols = {}
        total_inv_vol = 0.0
        
        for sym, vol in volatilities.items():
            if vol <= 0:
                vol = 0.0001
            inv = 1.0 / vol
            inv_vols[sym] = inv
            total_inv_vol += inv
            
        weights = {}
        for sym, inv in inv_vols.items():
            weights[sym] = inv / total_inv_vol
            
        return weights

    def leverage_to_target(self, weights: Dict[str, float], volatilities: Dict[str, float], target_portfolio_vol: float = 0.15) -> Dict[str, float]:
        """
        Apply leverage or deleverage to hit target portfolio volatility.
        Assuming 0 correlation for base calculation: Port_Vol = sqrt(sum(w_i^2 * vol_i^2)).
        Wait, in true risk parity with 0 correlation, w_i * vol_i is a constant C across all i.
        We scale all weights by target_portfolio_vol / current_portfolio_vol.
        """
        variance = 0.0
        for sym, w in weights.items():
            vol = volatilities[sym]
            variance += (w * vol) ** 2
            
        current_vol = np.sqrt(variance)
        if current_vol == 0:
            return weights
            
        scale_factor = target_portfolio_vol / current_vol
        
        scaled_weights = {sym: w * scale_factor for sym, w in weights.items()}
        
        total_weight = sum(scaled_weights.values())
        if total_weight > 1.0:
            logger.info(f"Leverage applied: Total allocation {total_weight*100:.1f}% to hit {target_portfolio_vol*100:.1f}% target vol.")
        else:
            logger.info(f"De-leveraging: Total allocation {total_weight*100:.1f}% to hit {target_portfolio_vol*100:.1f}% target vol.")
            
        return scaled_weights

    def correlation_adjustment(self, weights: Dict[str, float], returns_dict: Dict[str, np.ndarray]) -> Dict[str, float]:
        """
        After risk-parity weights, adjust for pairwise correlations.
        If two assets have correlation > 0.8, reduce COMBINED allocation by 20%.
        """
        symbols = list(weights.keys())
        adjusted_weights = weights.copy()
        
        for i in range(len(symbols)):
            for j in range(i + 1, len(symbols)):
                sym1 = symbols[i]
                sym2 = symbols[j]
                
                arr1 = returns_dict.get(sym1, np.array([]))
                arr2 = returns_dict.get(sym2, np.array([]))
                
                min_len = min(len(arr1), len(arr2))
                if min_len < 2:
                    continue
                    
                arr1 = arr1[-min_len:]
                arr2 = arr2[-min_len:]
                
                r, _ = stats.pearsonr(arr1, arr2)
                
                if r > 0.80:
                    logger.warning(f"High correlation ({r:.2f}) between {sym1} and {sym2}. Reducing combined allocation by 20%.")
                    # Reduce both by 20%
                    adjusted_weights[sym1] *= 0.80
                    adjusted_weights[sym2] *= 0.80
                    
        return adjusted_weights

    def rebalance_trigger(self, current_weights: Dict[str, float], target_weights: Dict[str, float]) -> bool:
        """
        Rebalance when any asset's actual weight deviates >20% from target.
        """
        needs_rebalance = False
        for sym, target_w in target_weights.items():
            current_w = current_weights.get(sym, 0.0)
            
            if target_w > 0:
                deviation = abs(current_w - target_w) / target_w
                if deviation > 0.20:
                    needs_rebalance = True
                    logger.info(f"Rebalance triggered for {sym}. Deviation: {deviation*100:.1f}% > 20%.")
                    break
            elif current_w > 0:
                needs_rebalance = True
                break
                
        return needs_rebalance

    def process_daily(self, returns_dict: Dict[str, np.ndarray], current_weights: Dict[str, float], target_portfolio_vol: float = 0.15) -> Dict[str, float]:
        """
        Run daily. Calculate vols, allocate, scale, adjust correlation, and check rebalance.
        Store in SQLite.
        """
        volatilities = {}
        for sym, returns in returns_dict.items():
            volatilities[sym] = self.calculate_asset_volatility(returns)
            
        # 1. Base Inverse Vol Allocation
        base_weights = self.risk_budget_allocation(volatilities)
        
        # 2. Leverage to target
        scaled_weights = self.leverage_to_target(base_weights, volatilities, target_portfolio_vol)
        
        # 3. Correlation Adjustment
        final_weights = self.correlation_adjustment(scaled_weights, returns_dict)
        
        # 4. Check Rebalance
        is_triggered = self.rebalance_trigger(current_weights, final_weights)
        
        # Store to DB
        with database_manager.session_scope() as session:
            for sym, weight in final_weights.items():
                record = RiskParityAllocations(
                    date=date.today(),
                    symbol=sym,
                    volatility=volatilities[sym],
                    allocation_weight=weight,
                    target_vol_contribution=target_portfolio_vol / len(final_weights) if len(final_weights) > 0 else 0.0,
                    is_rebalance_triggered=is_triggered
                )
                session.add(record)
                
        return final_weights
