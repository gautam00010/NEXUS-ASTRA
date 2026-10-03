"""Riskfolio-Lib Engine for advanced portfolio optimization."""
import riskfolio as rp
import pandas as pd
import numpy as np

class RiskfolioOptimizer:
    def __init__(self):
        self.model = 'Classic'
        self.rm = 'MV'
        self.obj = 'Sharpe'
        
    def optimize_portfolio(self, returns_df: pd.DataFrame) -> dict:
        """
        Calculates exact risk allocation using Riskfolio-Lib.
        Requires a DataFrame of historical returns for multiple assets.
        """
        port = rp.Portfolio(returns=returns_df)
        port.assets_stats(method_mu='hist', method_cov='hist')
        weights = port.optimization(model=self.model, rm=self.rm, obj=self.obj, rf=0.0)
        
        if weights is None or weights.empty:
            return {}
            
        return {k: round(float(v), 4) for k, v in weights.to_dict()['weights'].items()}


def optimize_portfolio(returns_df: pd.DataFrame | None = None) -> dict:
    """
    Direct function to calculate optimal risk weights using Riskfolio-Lib.
    """
    if returns_df is None:
        np.random.seed(42)
        dates = pd.date_range("2026-01-01", periods=100, freq="B")
        r_rel = np.random.normal(0.0010, 0.015, 100)
        r_tcs = np.random.normal(0.0008, 0.012, 100)
        r_infy = np.random.normal(0.0009, 0.014, 100)
        returns_df = pd.DataFrame(
            {"RELIANCE": r_rel, "TCS": r_tcs, "INFY": r_infy},
            index=dates
        )
    
    opt = RiskfolioOptimizer()
    return opt.optimize_portfolio(returns_df)
