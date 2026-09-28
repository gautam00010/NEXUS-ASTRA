"""Fat-Tail Risk Manager using Student's t-distribution for extreme risk sizing."""

from __future__ import annotations

import logging
from datetime import date
from typing import Dict, List, Tuple

import numpy as np
from scipy import stats

from nexus_astra.data_ingestion.database import TailRiskParams, database_manager

logger = logging.getLogger(__name__)


class FatTailRiskManager:
    """Manages tail risk by modeling returns with Student's t-distribution."""

    def __init__(self) -> None:
        pass

    def fit_t_distribution(self, returns: np.ndarray | List[float]) -> Tuple[float, float, float]:
        """
        Fit Student's t-distribution to historical daily returns.
        Returns: (degrees of freedom, mean (loc), scale)
        """
        arr = np.asarray(returns, dtype=float)
        if len(arr) < 3:
            return (10.0, 0.0, np.std(arr) if len(arr) > 1 else 0.01)
            
        df_t, loc_t, scale_t = stats.t.fit(arr)
        return float(df_t), float(loc_t), float(scale_t)

    def calculate_var_t(self, returns: np.ndarray | List[float], confidence: float = 0.99) -> Dict[str, float]:
        """
        Parametric VaR using t-distribution.
        Compares to normal VaR to report underestimation.
        """
        arr = np.asarray(returns, dtype=float)
        
        # t-distribution VaR
        df_t, loc_t, scale_t = self.fit_t_distribution(arr)
        # VaR is typically a negative number representing the loss threshold (e.g. -0.08)
        var_t = float(stats.t.ppf(1.0 - confidence, df_t, loc=loc_t, scale=scale_t))
        
        # Normal distribution VaR
        loc_n, scale_n = np.mean(arr), np.std(arr)
        var_n = float(stats.norm.ppf(1.0 - confidence, loc=loc_n, scale=scale_n))
        
        # If variances are 0, handle cleanly
        if scale_t == 0 or scale_n == 0:
            var_t = 0.0
            var_n = 0.0
            underestimation_pct = 0.0
        else:
            # Underestimation = (Normal VaR - t VaR) / abs(t VaR)
            # Since VaR is negative, if t VaR is -0.08 and norm VaR is -0.05, 
            # Norm underestimates loss. Difference in absolute terms: abs(-0.08) - abs(-0.05) = 0.03
            # Percent = 0.03 / 0.05 = 60% underestimation?
            # Or (abs(var_t) / abs(var_n)) - 1
            if var_n != 0:
                underestimation_pct = (abs(var_t) / abs(var_n)) - 1.0
            else:
                underestimation_pct = 0.0
                
        return {
            "df": df_t,
            "loc": loc_t,
            "scale": scale_t,
            "var_99": var_t,
            "normal_var_99": var_n,
            "underestimation_pct": underestimation_pct * 100.0
        }

    def position_size_from_tail_risk(self, var_99: float, max_daily_loss_pct: float = 5.0) -> float:
        """
        Position size = max_daily_loss_pct / |var_99| (assuming var_99 is fractional).
        E.g., if var_99 = -0.08 (8%), and max_loss = 5%, size = 5/8 = 62.5% = 0.625.
        """
        if var_99 == 0.0:
            return 1.0 # Default full size if no risk measurable
            
        var_pct = abs(var_99) * 100.0
        size = max_daily_loss_pct / var_pct
        return float(min(size, 1.0)) # Cap at 1.0 (100% position) unless leveraging is allowed

    def stress_test_regime(self, regime_label: str, returns: np.ndarray | List[float]) -> Dict[str, float]:
        """
        Calculate separate t-distribution parameters per regime.
        Store in SQLite TailRiskParams.
        """
        stats_dict = self.calculate_var_t(returns, confidence=0.99)
        
        with database_manager.session_scope() as session:
            existing = session.query(TailRiskParams).filter_by(
                date=date.today(),
                regime=regime_label
            ).first()
            
            if existing:
                existing.df = stats_dict["df"]
                existing.loc = stats_dict["loc"]
                existing.scale = stats_dict["scale"]
                existing.var_99 = stats_dict["var_99"]
                existing.normal_var_99 = stats_dict["normal_var_99"]
                existing.underestimation_pct = stats_dict["underestimation_pct"]
            else:
                record = TailRiskParams(
                    date=date.today(),
                    regime=regime_label,
                    df=stats_dict["df"],
                    loc=stats_dict["loc"],
                    scale=stats_dict["scale"],
                    var_99=stats_dict["var_99"],
                    normal_var_99=stats_dict["normal_var_99"],
                    underestimation_pct=stats_dict["underestimation_pct"]
                )
                session.add(record)
                
        logger.info(f"Regime '{regime_label}' Tail Risk stored. t-VaR99: {stats_dict['var_99']*100:.2f}%. Underestimation by Normal: {stats_dict['underestimation_pct']:.1f}%.")
        return stats_dict
