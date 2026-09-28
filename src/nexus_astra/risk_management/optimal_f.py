"""Optimal f calculation engine for position sizing."""

from __future__ import annotations

import logging
from datetime import date
from typing import Dict, List, Tuple

import numpy as np
from scipy.optimize import minimize_scalar

from nexus_astra.data_ingestion.database import OptimalFHistory, database_manager

logger = logging.getLogger(__name__)


class OptimalF:
    """Calculates Optimal f based on Ralph Vince's formula."""

    def __init__(self, historical_returns: List[float]) -> None:
        """
        Initialize with a sequence of historical returns.
        :param historical_returns: List of fractional returns (e.g., 0.05 for 5% win, -0.02 for 2% loss).
        """
        self.returns = np.array(historical_returns, dtype=float)

    def calculate_optimal_f(self, returns_array: np.ndarray | None = None) -> float:
        """
        Find the fraction f that maximizes TWR = ∏(1 + f × (-trade_return / max_drawdown_trade)).
        """
        if returns_array is None:
            returns_array = self.returns

        if len(returns_array) == 0:
            return 0.0

        # Find the maximum drawdown trade (the most negative return)
        max_loss = np.min(returns_array)
        
        # If there are no losing trades, theoretically we can bet 100% (or infinity). Cap at 1.0.
        if max_loss >= 0:
            return 1.0

        def objective_function(f: float) -> float:
            # HPR = 1 + f * (-trade_return / max_loss)
            # We want to maximize TWR = product(HPR), which is the same as maximizing sum(log(HPR))
            # We minimize the negative sum of log HPRs
            hpr = 1.0 + f * (-returns_array / max_loss)
            
            # If any HPR <= 0, the log is undefined (capital is wiped out), penalize heavily
            if np.any(hpr <= 0):
                return 1e9

            return -np.sum(np.log(hpr))

        # Use Brent's method bounded between 0 and 1
        res = minimize_scalar(objective_function, bounds=(0.0, 1.0), method='bounded')
        
        if res.success:
            return float(res.x)
        return 0.0

    def monte_carlo_validation(self, iterations: int = 10000) -> Tuple[float, float, float]:
        """
        Resample the trade sequence 10,000 times with replacement. 
        Calculate optimal f for each resample.
        Report 5th percentile, median, and 95th percentile.
        """
        if len(self.returns) == 0:
            return 0.0, 0.0, 0.0
            
        optimal_f_values = np.zeros(iterations)
        n = len(self.returns)
        
        # Optimize performance by pre-computing max_loss for each sample if possible,
        # but max_loss can vary per sample.
        
        for i in range(iterations):
            # Resample with replacement
            sample = np.random.choice(self.returns, size=n, replace=True)
            optimal_f_values[i] = self.calculate_optimal_f(sample)
            
        conservative_f = float(np.percentile(optimal_f_values, 5))
        median_f = float(np.percentile(optimal_f_values, 50))
        aggressive_f = float(np.percentile(optimal_f_values, 95))
        
        return conservative_f, median_f, aggressive_f

    def apply_fractional_f(self, f_value: float, fraction: float = 0.5) -> float:
        """
        Return fraction * optimal_f for live trading.
        Commonly known as Half-Optimal f.
        """
        return f_value * fraction

    @classmethod
    def per_signal_type(cls, trades_by_signal: Dict[str, List[float]]) -> Dict[str, Dict[str, float]]:
        """
        Calculate separate optimal f for each signal type.
        Stores results in OptimalFHistory table.
        """
        results = {}
        with database_manager.session_scope() as session:
            for signal_type, returns in trades_by_signal.items():
                if not returns:
                    continue
                    
                engine = cls(returns)
                opt_f = engine.calculate_optimal_f()
                cons_f, med_f, agg_f = engine.monte_carlo_validation(iterations=1000) # Using 1000 to save compute if many signals, or 10000
                
                results[signal_type] = {
                    "optimal_f": opt_f,
                    "conservative_f": cons_f,
                    "median_f": med_f,
                    "aggressive_f": agg_f
                }
                
                # Check for existing
                existing = session.query(OptimalFHistory).filter_by(
                    date=date.today(),
                    signal_type=signal_type
                ).first()
                
                if not existing:
                    history = OptimalFHistory(
                        date=date.today(),
                        signal_type=signal_type,
                        optimal_f=opt_f,
                        conservative_f=cons_f,
                        median_f=med_f,
                        aggressive_f=agg_f
                    )
                    session.add(history)
                    
        return results
