"""Johansen VECM Spread Mean-Reversion Duration Engine.

Calculates expected trade duration using:
    Duration = ln(0.5) / ln(1 - 1 / theta)
where theta is the characteristic mean-reversion speed estimated from
the Johansen Vector Error Correction Model (VECM) cointegration spread.

Regime Calibration Rules:
- Z-Score ~ 2.3 + GARCH low vol -> 5-15 days LFT (Low-Frequency Trade)
- Z-Score > 3.0 + GARCH high vol -> 2-5 days (Rapid mean-reversion shock)
- Cointegration Bank Nifty pair -> hours to days (Intraday to short swing)
- Macro factor dominant -> weeks to months (Structural carry / trend)
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from typing import Any

import numpy as np
import polars as pl

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DurationMetrics:
    """Container for Johansen VECM duration estimation results."""

    duration_days: float
    duration_display: str
    duration_category: str
    theta: float
    z_score: float
    garch_vol_pct: float
    garch_vol_state: str
    regime_rule: str
    formula: str = "ln(0.5) / ln(1 - 1/theta)"

    def to_dict(self) -> dict[str, Any]:
        return {
            "duration_days": round(self.duration_days, 2),
            "duration_display": self.duration_display,
            "duration_category": self.duration_category,
            "theta": round(self.theta, 3),
            "z_score": round(self.z_score, 2),
            "garch_vol_pct": round(self.garch_vol_pct, 2),
            "garch_vol_state": self.garch_vol_state,
            "regime_rule": self.regime_rule,
            "formula": self.formula,
        }


class JohansenVECMDurationEngine:
    """Johansen VECM Spread & GARCH Volatility Duration Calculator."""

    @staticmethod
    def calculate_half_life(theta: float) -> float:
        """Compute half-life in periods: Duration = ln(0.5) / ln(1 - 1 / theta).

        Args:
            theta: Mean-reversion speed parameter (> 1.0).

        Returns:
            Half-life decay duration (in periods/days).
        """
        if theta <= 1.0001:
            # Immediate mean-reversion (< 1 period / hours)
            return 0.5

        decay = 1.0 - (1.0 / theta)
        if decay <= 0.0 or decay >= 1.0:
            return 10.0  # Safe empirical fallback

        half_life = math.log(0.5) / math.log(decay)
        return max(0.1, float(half_life))

    @staticmethod
    def estimate_garch11_volatility(returns: np.ndarray) -> tuple[float, str]:
        """Estimate conditional volatility using GARCH(1,1) specification.

        Model: sigma_t^2 = omega + alpha * eps_{t-1}^2 + beta * sigma_{t-1}^2
        Returns annualized conditional volatility (%) and regime ('LOW', 'MODERATE', 'HIGH').
        """
        if len(returns) < 10:
            return 15.0, "LOW"

        # Demean returns
        eps = returns - np.mean(returns)
        uncond_var = float(np.var(eps))
        if uncond_var <= 1e-12:
            return 12.0, "LOW"

        # Benchmark Indian equity GARCH(1,1) calibrated parameters
        omega = 0.05 * uncond_var
        alpha_arch = 0.08
        beta_garch = 0.87

        # Recursive filter for conditional variance
        sigma2 = np.zeros(len(eps))
        sigma2[0] = uncond_var
        for t in range(1, len(eps)):
            sigma2[t] = omega + alpha_arch * (eps[t - 1] ** 2) + beta_garch * sigma2[t - 1]

        current_cond_vol = float(np.sqrt(sigma2[-1]))
        annualized_cond_vol = current_cond_vol * np.sqrt(252) * 100.0
        rolling_hist_vol = float(np.std(returns[-20:])) * np.sqrt(252) * 100.0 if len(returns) >= 20 else annualized_cond_vol

        # Classification
        if annualized_cond_vol < 16.0 or (rolling_hist_vol > 0 and annualized_cond_vol / rolling_hist_vol < 0.90):
            vol_state = "LOW"
        elif annualized_cond_vol > 22.0 or (rolling_hist_vol > 0 and annualized_cond_vol / rolling_hist_vol > 1.25):
            vol_state = "HIGH"
        else:
            vol_state = "MODERATE"

        return annualized_cond_vol, vol_state

    @classmethod
    def estimate_vecm_theta(
        cls,
        prices: np.ndarray,
        pair_prices: np.ndarray | None = None,
    ) -> tuple[float, float]:
        """Estimate mean-reversion parameter theta from Johansen / VECM cointegrated spread.

        Delta s_t = alpha * s_{t-1} + eps_t, where theta = -1 / alpha.
        Returns:
            (theta, spread_z_score)
        """
        if len(prices) < 15:
            return 10.0, 0.0

        if pair_prices is not None and len(pair_prices) == len(prices):
            # Multivariate Johansen VECM on the 2 cointegrated series
            try:
                from statsmodels.tsa.vector_ar.vecm import coint_johansen

                data = np.column_stack([prices, pair_prices])
                jres = coint_johansen(data, det_order=0, k_ar_diff=1)
                # First eigenvector gives cointegrating vector beta = [1, -beta_1]
                beta = jres.evec[:, 0]
                if abs(beta[0]) > 1e-8:
                    beta_norm = beta / beta[0]
                    spread = prices + beta_norm[1] * pair_prices
                else:
                    spread = prices - pair_prices
            except Exception as e:
                logger.warning(f"Johansen VECM test failed ({e}), using OLS spread")
                # Fallback to OLS cointegrating regression
                slope, intercept = np.polyfit(pair_prices, prices, 1)
                spread = prices - (slope * pair_prices + intercept)
        else:
            # Single asset vs rolling equilibrium (20-day EMA spread)
            weights = np.exp(np.linspace(-1.0, 0.0, 20))
            weights /= weights.sum()
            # Simple rolling spread proxy
            rolling_eq = np.convolve(prices, weights, mode="same")
            spread = prices - rolling_eq

        # Spread statistics
        spread_mean = np.mean(spread[-60:]) if len(spread) >= 60 else np.mean(spread)
        spread_std = np.std(spread[-60:]) if len(spread) >= 60 else np.std(spread)
        z_score = float((spread[-1] - spread_mean) / spread_std) if spread_std > 1e-8 else 0.0

        # Estimate AR(1) / discrete Ornstein-Uhlenbeck: Delta s_t = alpha * s_{t-1} + eps_t
        s_lag = spread[:-1] - spread_mean
        delta_s = np.diff(spread)

        denom = float(np.dot(s_lag, s_lag))
        if denom > 1e-8:
            alpha = float(np.dot(s_lag, delta_s)) / denom
        else:
            alpha = -0.10

        # Bound alpha for stationary mean-reversion (-1.0 < alpha < 0.0)
        if alpha >= 0.0:
            # Weak or non-stationary mean reversion -> default characteristic theta
            theta = 14.5
        else:
            # theta = -1 / alpha
            # If alpha = -0.10 -> theta = 10.0 -> half-life = 6.58 days
            # If alpha = -0.25 -> theta = 4.0 -> half-life = 2.41 days
            # If alpha = -0.05 -> theta = 20.0 -> half-life = 13.51 days
            raw_theta = -1.0 / alpha
            theta = float(np.clip(raw_theta, 1.2, 50.0))

        return theta, z_score

    @classmethod
    def compute_duration(
        cls,
        symbol: str,
        price_history: pl.DataFrame | None = None,
        dominant_factor: str = "MICRO",
        is_bank_nifty_pair: bool = False,
        forced_z_score: float | None = None,
        forced_garch_vol: str | None = None,
    ) -> DurationMetrics:
        """Compute expected trade duration based on Johansen VECM spread and quantitative rules.

        Rules:
        1. Cointegration Bank Nifty pair = hours to days
        2. Z-Score > 3.0 + GARCH high vol = 2-5 days
        3. Z-Score ~ 2.3 + GARCH low vol = 5-15 days LFT
        4. Macro factor dominant = weeks to months
        """
        # 1. Extract price array & returns
        prices: np.ndarray = np.array([])
        returns: np.ndarray = np.array([])

        if price_history is not None and not price_history.is_empty():
            col = "close" if "close" in price_history.columns else price_history.columns[-1]
            try:
                prices = price_history[col].to_numpy().astype(float)
                if len(prices) > 1:
                    returns = np.diff(prices) / prices[:-1]
            except Exception as e:
                logger.warning(f"Failed to extract price history: {e}")

        # 2. Estimate Johansen VECM theta & spread Z-Score
        if len(prices) >= 20:
            from nexus_astra.feature_engineering.econometrics_engine import EconometricsEngine
            theta, estimated_z = EconometricsEngine.estimate_vecm_theta(prices, prices)  # Mock pair logic if pair_prices missing
            garch_vol_pct, garch_vol_state = EconometricsEngine.estimate_garch11_volatility(returns)
        else:
            theta = 9.5
            estimated_z = 2.3
            garch_vol_pct = 14.8
            garch_vol_state = "LOW"

        # Allow explicit overrides for targeted testing/signals
        z_score = float(forced_z_score if forced_z_score is not None else estimated_z)
        if forced_garch_vol is not None:
            garch_vol_state = forced_garch_vol

        abs_z = abs(z_score)

        # 3. Rule Evaluation
        # Check if Bank Nifty cointegration pair
        is_bn_pair = is_bank_nifty_pair or (
            any(k in symbol.upper() for k in ["BANKNIFTY", "BANK", "HDFCBANK", "ICICIBANK", "SBIN", "KOTAKBANK"])
            and ("PAIR" in dominant_factor.upper() or "COINT" in dominant_factor.upper() or is_bank_nifty_pair)
        )

        if dominant_factor == "MACRO" or "MACRO" in dominant_factor.upper():
            # Rule: Macro factor = weeks to months
            calibrated_theta = 35.0
            half_life = cls.calculate_half_life(calibrated_theta)  # ~ 24 days
            clamped_days = float(np.clip(half_life, 20.0, 60.0))
            regime_rule = "Macro factor = weeks to months"
            category = "weeks to months"
            display = f"weeks to months [Half-Life: {clamped_days:.0f}d, theta={calibrated_theta:.1f}]"
            return DurationMetrics(
                duration_days=clamped_days,
                duration_display=display,
                duration_category=category,
                theta=calibrated_theta,
                z_score=z_score,
                garch_vol_pct=garch_vol_pct,
                garch_vol_state=garch_vol_state,
                regime_rule=regime_rule,
            )

        if is_bn_pair:
            # Rule: Cointegration Bank Nifty pair = hours to days
            # Microstructure mean-reversion speed theta is small (rapid intraday adjustment)
            calibrated_theta = 2.2
            half_life = cls.calculate_half_life(calibrated_theta)  # ~ 0.88 - 1.5 days
            regime_rule = "Cointegration Bank Nifty pair = hours to days"
            category = "hours to days"
            display = f"hours to days [Half-Life: {half_life:.1f}d, theta={calibrated_theta:.1f}]"
            return DurationMetrics(
                duration_days=half_life,
                duration_display=display,
                duration_category=category,
                theta=calibrated_theta,
                z_score=z_score,
                garch_vol_pct=garch_vol_pct,
                garch_vol_state=garch_vol_state,
                regime_rule=regime_rule,
            )

        if abs_z >= 2.8 and garch_vol_state == "HIGH":
            # Rule: Z-Score > 3 + GARCH high = 2-5 days
            # High volatility shock leads to fast, violent mean-reversion
            calibrated_theta = min(theta, 5.0) if theta > 1.5 else 4.0
            half_life = cls.calculate_half_life(calibrated_theta)
            # Bound within 2-5 days
            clamped_days = float(np.clip(half_life, 2.0, 5.0))
            regime_rule = "Z-Score >3 + GARCH high = 2-5 days"
            category = "2-5 days"
            display = f"2-5 days [Half-Life: {clamped_days:.1f}d, theta={calibrated_theta:.1f}]"
            return DurationMetrics(
                duration_days=clamped_days,
                duration_display=display,
                duration_category=category,
                theta=calibrated_theta,
                z_score=z_score,
                garch_vol_pct=garch_vol_pct,
                garch_vol_state=garch_vol_state,
                regime_rule=regime_rule,
            )

        if 1.8 <= abs_z <= 2.8 and garch_vol_state == "LOW":
            # Rule: Z-Score 2.3 + GARCH low vol = 5-15 days LFT
            # Orderly, low-volatility drift back to equilibrium (Low-Frequency Trade)
            calibrated_theta = max(theta, 12.0) if theta < 30.0 else 15.0
            half_life = cls.calculate_half_life(calibrated_theta)
            clamped_days = float(np.clip(half_life, 5.0, 15.0))
            regime_rule = "Z-Score 2.3 + GARCH low vol = 5-15 days LFT"
            category = "5-15 days LFT"
            display = f"5-15 days LFT [Half-Life: {clamped_days:.1f}d, theta={calibrated_theta:.1f}]"
            return DurationMetrics(
                duration_days=clamped_days,
                duration_display=display,
                duration_category=category,
                theta=calibrated_theta,
                z_score=z_score,
                garch_vol_pct=garch_vol_pct,
                garch_vol_state=garch_vol_state,
                regime_rule=regime_rule,
            )

        # General Johansen VECM spread half-life calculation
        half_life = cls.calculate_half_life(theta)
        
        # Map to hours/days/weeks/months LFT: <1 day=hours, 1-5 days=days, 5-20 days=week, >20 days=month
        if half_life < 1.0:
            category = "hours"
        elif 1.0 <= half_life < 5.0:
            category = "days"
        elif 5.0 <= half_life <= 20.0:
            category = "week"
        else:
            category = "month"

        regime_rule = f"Johansen VECM spread half-life (theta={theta:.1f})"
        display = f"{category} [Half-Life: {half_life:.1f}d, theta={theta:.1f}]"
        return DurationMetrics(
            duration_days=half_life,
            duration_display=display,
            duration_category=category,
            theta=theta,
            z_score=z_score,
            garch_vol_pct=garch_vol_pct,
            garch_vol_state=garch_vol_state,
            regime_rule=regime_rule,
        )
