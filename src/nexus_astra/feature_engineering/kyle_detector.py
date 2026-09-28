"""Kyle (1985) Market Microstructure model for detecting informed trading."""

from __future__ import annotations

import logging
from datetime import date
from typing import Dict, Any, List

import numpy as np
import polars as pl

from nexus_astra.data_ingestion.database import InformedFlowMetrics, database_manager

logger = logging.getLogger(__name__)


class KyleInformedFlow:
    """Detects informed order flow using Kyle's Lambda and order flow imbalances."""

    def __init__(self) -> None:
        pass

    def calculate_lambda(self, price_change: float, signed_volume: float) -> float:
        """
        Kyle's lambda = price_change / signed_volume.
        Measures the price impact of a given trade volume.
        High lambda means it takes very little volume to move the price -> lack of liquidity / high information asymmetry.
        """
        if signed_volume == 0:
            return 0.0
        # Typically lambda is strictly positive (price change follows volume direction)
        return abs(price_change / signed_volume)

    def informed_probability(self, symbol: str, df: pl.DataFrame, period: int = 20) -> pl.DataFrame:
        """
        Using a rolling window, estimate probability that current order flow is informed.
        Expects df with: 'price_change', 'signed_volume'.
        If lambda spikes > 2 std dev from mean -> INFORMED_TRADING_DETECTED.
        Returns DF with new columns: 'lambda', 'lambda_mean', 'lambda_std', 'is_informed'.
        """
        # Calculate raw lambda natively in polars
        # Handle zero division
        df = df.with_columns(
            pl.when(pl.col("signed_volume") != 0)
            .then((pl.col("price_change") / pl.col("signed_volume")).abs())
            .otherwise(0.0)
            .alias("lambda")
        )
        
        # Calculate rolling stats
        df = df.with_columns([
            pl.col("lambda").rolling_mean(window_size=period).alias("lambda_mean"),
            pl.col("lambda").rolling_std(window_size=period).alias("lambda_std")
        ])
        
        # Flag spikes > 2 std dev
        df = df.with_columns(
            (
                (pl.col("lambda") > (pl.col("lambda_mean") + 2 * pl.col("lambda_std"))) & 
                (pl.col("lambda_std").is_not_null()) & 
                (pl.col("lambda_std") > 0)
            ).alias("is_informed")
        )
        
        return df

    def order_flow_imbalance(self, buy_volume: float, sell_volume: float) -> float:
        """
        OFI = (Buy volume - Sell volume) / Total volume.
        """
        total_vol = buy_volume + sell_volume
        if total_vol == 0:
            return 0.0
            
        return (buy_volume - sell_volume) / total_vol

    def evaluate_flow(
        self, 
        symbol: str, 
        buy_volume: float, 
        sell_volume: float, 
        current_lambda: float, 
        lambda_mean: float, 
        lambda_std: float
    ) -> Dict[str, Any]:
        """
        Check if imbalance > 70% AND lambda elevated -> strong informed buying.
        """
        ofi = self.order_flow_imbalance(buy_volume, sell_volume)
        
        is_lambda_elevated = False
        if lambda_std > 0 and current_lambda > (lambda_mean + 2 * lambda_std):
            is_lambda_elevated = True
            
        strong_buying = False
        if ofi > 0.70 and is_lambda_elevated:
            strong_buying = True
            logger.warning(f"STRONG INFORMED BUYING DETECTED for {symbol}: OFI {ofi*100:.1f}%, Lambda {current_lambda:.6f}")
            
        # Store metrics
        with database_manager.session_scope() as session:
            record = InformedFlowMetrics(
                date=date.today(),
                symbol=symbol,
                lambda_value=current_lambda,
                is_informed_detected=is_lambda_elevated,
                order_flow_imbalance=ofi,
                strong_buying=strong_buying
            )
            session.add(record)
            
        return {
            "symbol": symbol,
            "lambda": current_lambda,
            "ofi": ofi,
            "is_informed": is_lambda_elevated,
            "strong_buying": strong_buying
        }

    def block_deal_kyle_filter(
        self, 
        symbol: str, 
        deal_value_cr: float, 
        pre_price_change: float, 
        pre_volume: float, 
        post_price_change: float, 
        post_volume: float
    ) -> Dict[str, Any]:
        """
        For block deals > ₹10 Cr, calculate lambda in 30 mins before and after.
        If post-deal lambda > pre-deal lambda * 2 -> deal was informed.
        """
        if deal_value_cr < 10.0:
            return {"status": "IGNORED", "reason": "< 10 Cr"}
            
        pre_lambda = self.calculate_lambda(pre_price_change, pre_volume)
        post_lambda = self.calculate_lambda(post_price_change, post_volume)
        
        is_informed = False
        impact_str = "Neutral"
        
        # If pre_lambda is 0, we can't do a clean multiplier check.
        # But if post_lambda is massive, it might still be informed.
        if pre_lambda > 0:
            if post_lambda > (pre_lambda * 2.0):
                is_informed = True
                impact_str = f"Informed! Post-Lambda {post_lambda:.6f} > 2x Pre-Lambda {pre_lambda:.6f}"
                logger.warning(f"BLOCK DEAL KYLE DETECTOR: {symbol} - {impact_str}")
            else:
                impact_str = f"Temporary impact. Post {post_lambda:.6f} vs Pre {pre_lambda:.6f}"
        elif post_lambda > 0:
            is_informed = True
            impact_str = "Informed! Zero pre-impact, massive post-impact."
            
        with database_manager.session_scope() as session:
            record = InformedFlowMetrics(
                date=date.today(),
                symbol=f"{symbol}_BLOCK",
                lambda_value=post_lambda,
                is_informed_detected=is_informed,
                order_flow_imbalance=0.0,
                strong_buying=False,
                block_deal_impact=impact_str
            )
            session.add(record)
            
        return {
            "symbol": symbol,
            "pre_lambda": pre_lambda,
            "post_lambda": post_lambda,
            "is_informed": is_informed,
            "impact_string": impact_str
        }
