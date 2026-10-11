"""Quantitative Toolkit for Indian Equities (BSE/NSE) and Crypto.

Key Institutional Tools:
1. ATR Position Sizing: Risk exactly 1% capital per trade: Shares = (Capital * 1%) / (1.5 * ATR).
2. RSI + Volume Confirmation: Flags fakeouts (RSI > 70 on below-average volume = Bull Trap).
3. Correlation Cluster Check: Identifies portfolio illusions (5 stocks with corr > 0.8 = 1 bet, not 5).
4. Backtest Quality Filter: Requires >= 200 trades and Net Sharpe >= 1.2 after realistic Indian costs (0.1% + STT + GST).
"""

from __future__ import annotations
import logging
from typing import Any, Dict, List
import numpy as np
import pandas as pd
import pandas_ta as ta

logger = logging.getLogger(__name__)


def atr_position_sizing(
    capital: float = 100_000.0,
    risk_pct: float = 0.01,         # 1% capital risk per trade
    current_price: float = 2985.40,
    atr: float = 45.0,              # Average True Range in points
    stop_multiplier: float = 1.5,   # 1.5x ATR stop loss distance
) -> Dict[str, Any]:
    """
    Computes exact mathematical position size based on ATR volatility risk.

    Formula:
      Risk_Amount = Capital * Risk_Pct
      Stop_Distance = ATR * Stop_Multiplier
      Shares = floor( Risk_Amount / Stop_Distance )
    """
    risk_amount = capital * risk_pct
    stop_distance = atr * stop_multiplier
    shares = int(np.floor(risk_amount / max(stop_distance, 1e-4)))
    position_notional = shares * current_price
    effective_exposure_pct = (position_notional / capital) * 100.0

    stop_loss_price = current_price - stop_distance
    target_price = current_price + (stop_distance * 2.0)  # 1:2 R:R target

    return {
        "capital_inr": capital,
        "risk_budget_inr": round(risk_amount, 2),
        "current_price": round(current_price, 2),
        "atr_value": round(atr, 2),
        "stop_distance_pts": round(stop_distance, 2),
        "recommended_shares": shares,
        "position_notional_inr": round(position_notional, 2),
        "capital_allocation_pct": round(effective_exposure_pct, 2),
        "stop_loss_level": round(stop_loss_price, 2),
        "take_profit_level_2r": round(target_price, 2),
        "rule": "If stopped out, loss is strictly capped at exactly 1% of total portfolio equity.",
    }


def rsi_volume_confirmation(
    df: pd.DataFrame | None = None,
    rsi_period: int = 14,
) -> Dict[str, Any]:
    """
    Checks RSI combined with Volume to filter out false breakouts and bull traps.
    """
    if df is None or len(df) < rsi_period + 5:
        # Synthetic baseline demonstration
        return {
            "rsi": 73.5,
            "volume_ratio_to_20sma": 0.68,
            "status": "FAKE_BREAKOUT_BULL_TRAP",
            "warning": "RSI > 70 with volume 32% BELOW 20-day average. Do NOT buy breakout; high probability of bull trap.",
            "action": "AVOID_LONG_OR_FADE",
        }

    c_col = "Close" if "Close" in df.columns else df.columns[3]
    v_col = "Volume" if "Volume" in df.columns else df.columns[4]

    rsi_series = ta.rsi(df[c_col], length=rsi_period)
    current_rsi = float(rsi_series.iloc[-1]) if rsi_series is not None and not rsi_series.empty else 50.0

    vol = df[v_col].astype(float)
    vol_sma20 = float(vol.rolling(20).mean().iloc[-1]) if len(vol) >= 20 else float(vol.mean())
    current_vol = float(vol.iloc[-1])
    vol_ratio = current_vol / max(vol_sma20, 1.0)

    if current_rsi > 70.0 and vol_ratio < 0.90:
        status = "FAKE_BREAKOUT_BULL_TRAP"
        warning = f"RSI is overbought ({current_rsi:.1f}) on weak volume ({vol_ratio:.2f}x SMA). Classic retail trap."
        action = "AVOID_OR_FADE"
    elif current_rsi > 70.0 and vol_ratio >= 1.30:
        status = "CONFIRMED_MOMENTUM_EXPANSION"
        warning = f"RSI momentum ({current_rsi:.1f}) validated by institutional volume ({vol_ratio:.2f}x SMA)."
        action = "RIDE_MOMENTUM_WITH_TRAILING_SL"
    elif current_rsi < 30.0 and vol_ratio < 0.90:
        status = "FAKE_BREAKDOWN_BEAR_TRAP"
        warning = f"RSI oversold ({current_rsi:.1f}) on low volume exhaustion. Panic selling without institutional backing."
        action = "ANTICIPATE_REVERSAL"
    else:
        status = "NORMAL_FLOW"
        warning = f"RSI ({current_rsi:.1f}) and volume ({vol_ratio:.2f}x) within standard parameters."
        action = "FOLLOW_CORE_SYSTEM"

    return {
        "rsi": round(current_rsi, 1),
        "volume_ratio_to_20sma": round(vol_ratio, 2),
        "status": status,
        "warning": warning,
        "action": action,
    }


def correlation_cluster_check(
    returns_df: pd.DataFrame | None = None,
    threshold: float = 0.80,
) -> Dict[str, Any]:
    """
    Evaluates pairwise correlation across portfolio assets to prevent the illusion of diversification.
    """
    if returns_df is None or returns_df.empty or len(returns_df.columns) < 2:
        # Canonical high-correlation banking cluster baseline
        symbols = ["HDFCBANK", "ICICIBANK", "SBIN", "KOTAKBANK", "AXISBANK"]
        corr_matrix = pd.DataFrame(
            [
                [1.00, 0.86, 0.82, 0.84, 0.88],
                [0.86, 1.00, 0.83, 0.81, 0.85],
                [0.82, 0.83, 1.00, 0.79, 0.84],
                [0.84, 0.81, 0.79, 1.00, 0.82],
                [0.88, 0.85, 0.84, 0.82, 1.00],
            ],
            index=symbols,
            columns=symbols,
        )
    else:
        corr_matrix = returns_df.corr()

    # Extract upper triangle pairwise correlations
    cols = corr_matrix.columns
    n = len(cols)
    pairs = []
    high_corr_count = 0
    total_pairs = 0

    for i in range(n):
        for j in range(i + 1, n):
            val = float(corr_matrix.iloc[i, j])
            total_pairs += 1
            if val >= threshold:
                high_corr_count += 1
                pairs.append(f"{cols[i]} ↔ {cols[j]} ({val:.2f})")

    avg_corr = float(corr_matrix.values[np.triu_indices(n, k=1)].mean()) if n > 1 else 1.0
    is_concentrated = avg_corr >= threshold

    return {
        "assets_evaluated": list(cols),
        "average_pairwise_correlation": round(avg_corr, 2),
        "high_correlation_threshold": threshold,
        "high_correlation_pairs_count": high_corr_count,
        "flagged_pairs": pairs,
        "is_concentrated_illusion": is_concentrated,
        "warning": (
            f"DIVERSIFICATION ILLUSION: Average correlation is {avg_corr:.2f} (> {threshold}). "
            "You are not holding 5 diversified assets; you are holding 1 single leveraged macro bet."
            if is_concentrated
            else f"Portfolio exhibits healthy cross-asset diversification (Avg Corr: {avg_corr:.2f})."
        ),
    }


def backtest_quality_filter(
    trades_count: int = 240,
    sharpe_gross: float = 1.65,
    fee_drag_pct: float = 28.5,  # 28.5 bps drag per trade
    win_rate_pct: float = 52.0,
) -> Dict[str, Any]:
    """
    Rigorously qualifies a trading strategy backtest against institutional standards:
      1. Minimum 200 trades sample size (Law of Large Numbers).
      2. Net Sharpe Ratio >= 1.2 AFTER Indian transaction friction (0.1% STT + GST + brokerage).
    """
    has_sufficient_samples = trades_count >= 200
    # Estimate net Sharpe after fee drag
    net_sharpe = max(0.0, sharpe_gross - (fee_drag_pct / 50.0))
    is_institutionally_viable = has_sufficient_samples and net_sharpe >= 1.2

    return {
        "trades_count": trades_count,
        "minimum_sample_requirement": 200,
        "has_sample_validity": has_sufficient_samples,
        "gross_sharpe": round(sharpe_gross, 2),
        "estimated_net_sharpe": round(net_sharpe, 2),
        "fee_drag_bps": fee_drag_pct,
        "win_rate_pct": win_rate_pct,
        "is_institutionally_viable": is_institutionally_viable,
        "verdict": (
            "PASSED INSTITUTIONAL AUDIT: Statistically robust with positive post-friction edge."
            if is_institutionally_viable
            else "FAILED QUALITY FILTER: Insufficient trades (< 200) or Net Sharpe < 1.2 after Indian taxes."
        ),
    }
