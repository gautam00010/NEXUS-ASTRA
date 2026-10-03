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
        # Initialize Portfolio object
        port = rp.Portfolio(returns=returns_df)
        
        # Calculate assets statistics (Mean and Covariance matrix)
        port.assets_stats(method_mu='hist', method_cov='hist')
        
        # Optimize portfolio
        weights = port.optimization(model=self.model, rm=self.rm, obj=self.obj, rf=0.0)
        
        if weights is None or weights.empty:
            return {}
            
        # Return portfolio weights as dictionary
        return weights.to_dict()['weights']
