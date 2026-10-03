"""Econometrics Engine (Johansen Cointegration & GARCH Volatility) using C/Fortran implementations."""
import numpy as np
from statsmodels.tsa.vector_ar.vecm import coint_johansen
from arch import arch_model
import logging

logger = logging.getLogger(__name__)

class EconometricsEngine:
    @staticmethod
    def estimate_vecm_theta(prices1: np.ndarray, prices2: np.ndarray) -> tuple[float, float]:
        """
        Estimates Johansen Cointegration Z-Score and mean-reversion parameter (theta).
        Uses statsmodels C/Fortran compiled vector_ar implementations.
        """
        try:
            data = np.column_stack([prices1, prices2])
            # Run Johansen cointegration test
            res = coint_johansen(data, det_order=0, k_ar_diff=1)
            
            # Extract eigenvector (cointegrating vector)
            beta = res.evec[:, 0]
            beta_norm = beta / beta[0]
            
            spread = prices1 + beta_norm[1] * prices2
            spread_mean = np.mean(spread)
            spread_std = np.std(spread)
            
            z_score = float((spread[-1] - spread_mean) / spread_std) if spread_std > 0 else 0.0
            
            # Simple AR(1) decay on spread for theta
            s_lag = spread[:-1] - spread_mean
            delta_s = np.diff(spread)
            alpha = float(np.dot(s_lag, delta_s)) / float(np.dot(s_lag, s_lag)) if np.dot(s_lag, s_lag) > 0 else -0.10
            
            theta = float(np.clip(-1.0 / alpha, 1.2, 50.0)) if alpha < 0 else 14.5
            
            return theta, z_score
        except Exception as e:
            logger.warning(f"Johansen VECM failed: {e}")
            return 10.0, 0.0

    @staticmethod
    def estimate_garch11_volatility(returns: np.ndarray) -> tuple[float, str]:
        """
        Estimates conditional volatility regime using GARCH(1,1).
        Uses bashtage's arch package compiled in C.
        """
        try:
            # Rescale returns for optimizer stability
            rescaled = returns * 100.0
            am = arch_model(rescaled, vol='Garch', p=1, q=1, dist='Normal', rescale=False)
            res = am.fit(disp='off')
            
            # Get latest conditional variance
            cond_var = res.conditional_volatility[-1] ** 2
            ann_vol = float(np.sqrt(cond_var) * np.sqrt(252))
            
            if ann_vol < 16.0:
                vol_state = "LOW"
            elif ann_vol > 22.0:
                vol_state = "HIGH"
            else:
                vol_state = "MODERATE"
                
            return ann_vol, vol_state
        except Exception as e:
            logger.warning(f"GARCH model failed: {e}")
            return 15.0, "LOW"
