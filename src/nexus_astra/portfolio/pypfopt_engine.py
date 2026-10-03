"""PyPortfolioOpt Engine for MPT, Black-Litterman, and fractional Kelly."""
import pandas as pd
from pypfopt import EfficientFrontier, risk_models, expected_returns, black_litterman
from pypfopt.black_litterman import BlackLittermanModel
import logging

logger = logging.getLogger(__name__)

class PyPortfolioOptEngine:
    @staticmethod
    def compute_max_sharpe(prices: pd.DataFrame) -> dict:
        """
        Computes the Maximum Sharpe Ratio portfolio using PyPortfolioOpt.
        """
        try:
            # Calculate expected returns and sample covariance
            mu = expected_returns.mean_historical_return(prices)
            S = risk_models.sample_cov(prices)
            ef = EfficientFrontier(mu, S)
            
            try:
                raw_weights = ef.max_sharpe(risk_free_rate=0.0)
            except Exception:
                raw_weights = ef.min_volatility()
            cleaned_weights = ef.clean_weights()
            
            return {k: round(float(v), 4) for k, v in cleaned_weights.items()}
        except Exception as e:
            logger.warning(f"PyPortfolioOpt Max Sharpe failed: {e}")
            # Robust equal-weight fallback
            cols = list(prices.columns)
            return {c: round(1.0 / len(cols), 4) for c in cols}

    @staticmethod
    def compute_kelly_fractional(win_rate: float, avg_win_pct: float, avg_loss_pct: float) -> float:
        """
        Computes 20% Fractional Kelly with hard caps:
        f* = [W*(R+1)-1]/R * 0.2
        Max 15% cap.
        """
        if avg_loss_pct <= 0:
            return 0.0
            
        R = avg_win_pct / avg_loss_pct
        kelly_raw = (win_rate * (R + 1.0) - 1.0) / R
        kelly_frac = max(0.0, kelly_raw * 0.20)
        
        # Max cap 15%
        return min(kelly_frac, 0.15)
