"""Dynamic Weighting Engine for Composite Signals."""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from typing import Dict, List, Any

import numpy as np
import polars as pl
from dataclasses import asdict, is_dataclass

from nexus_astra.data_ingestion.database import DynamicWeights, TradeLog, DailyPriceData, database_manager

logger = logging.getLogger(__name__)


class DynamicWeightEngine:
    """Calculates dynamically adjusted weights for all signal layers."""

    def __init__(self) -> None:
        pass

    def calculate_rolling_correlation(self, asset1_symbol: str, asset2_symbol: str, window: int = 30) -> float:
        """
        Calculate Rolling Pearson correlation between two assets over a given window.
        Uses DailyPriceData table.
        """
        with database_manager.session_scope() as session:
            rows = session.query(DailyPriceData).filter(
                DailyPriceData.symbol.in_([asset1_symbol, asset2_symbol])
            ).all()
            
        if not rows:
            return 0.0
            
        records: list[dict[str, Any]] = []
        for row in rows:
            record = asdict(row) if is_dataclass(row) else row.__dict__.copy()
            record.pop("_sa_instance_state", None)
            records.append(record)
            
        df = pl.DataFrame(records)
        if df.is_empty():
            return 0.0
            
        # Pivot so we have dates as rows and symbols as columns
        df_pivot = df.pivot(
            values="close",
            index="trade_date",
            on="symbol"
        ).sort("trade_date")
        
        if asset1_symbol not in df_pivot.columns or asset2_symbol not in df_pivot.columns:
            return 0.0
            
        # Drop nulls
        df_clean = df_pivot.drop_nulls()
        
        if len(df_clean) < window:
            return 0.0
            
        # Calculate trailing correlation of the last `window` rows
        tail_df = df_clean.tail(window)
        corr = tail_df.select(pl.corr(asset1_symbol, asset2_symbol)).item()
        
        # Handle cases where variance is 0
        if corr is None or np.isnan(corr):
            return 0.0
            
        return float(corr)

    def map_correlation_to_weight(self, correlation: float) -> float:
        """
        Linear interpolation for correlation to weight mapping:
        corr <= 0.0 -> 0%
        corr 0.3 -> 5%
        corr 0.5 -> 15%
        corr 0.7 -> 25%
        corr 0.85 -> 35%
        corr 0.9 -> 40%
        corr > 0.9 -> 40% (capped)
        """
        xp = [0.0, 0.3, 0.5, 0.7, 0.85, 0.9]
        fp = [0.0, 5.0, 15.0, 25.0, 35.0, 40.0]
        
        # Using numpy interp which handles capping automatically for bounds if left/right not specified,
        # but specifically we want to cap at 40 for >0.9, and floor at 0 for <0.0
        weight = np.interp(correlation, xp, fp, left=0.0, right=40.0)
        return float(weight)

    def apply_to_all_signals(self, current_us_correlation: float, active_signal_types: List[str]) -> Dict[str, float]:
        """
        Every signal gets a dynamic weight based on its predictive power (rolling 90-day accuracy).
        If accuracy drops below 50%, weight goes to 0 automatically.
        Weights are normalized to sum to 100%.
        """
        raw_weights = {}
        
        # Calculate raw weights based on 90-day accuracy
        cutoff_date = date.today() - timedelta(days=90)
        
        with database_manager.session_scope() as session:
            rows = session.query(TradeLog).filter(TradeLog.exit_date >= cutoff_date).all()
            
        records: list[dict[str, Any]] = []
        if rows:
            for row in rows:
                record = asdict(row) if is_dataclass(row) else row.__dict__.copy()
                record.pop("_sa_instance_state", None)
                records.append(record)
                
        df_trades = pl.DataFrame(records)
        
        for sig_type in active_signal_types:
            if sig_type == "US_LEAD_LAG":
                # Specific logic for US_LEAD_LAG overriding accuracy logic
                raw_weights[sig_type] = self.map_correlation_to_weight(current_us_correlation)
                continue
                
            if df_trades.is_empty() or "signal_type" not in df_trades.columns:
                accuracy = 0.50 # Default baseline if no history
            else:
                sig_trades = df_trades.filter(pl.col("signal_type") == sig_type)
                total_trades = len(sig_trades)
                
                if total_trades == 0:
                    accuracy = 0.50
                else:
                    winning_trades = len(sig_trades.filter(pl.col("pnl_pct") > 0))
                    accuracy = winning_trades / total_trades
            
            if accuracy < 0.50:
                raw_weights[sig_type] = 0.0
            else:
                # Raw weight is proportional to accuracy above 50%
                # E.g. accuracy 50% -> weight 50, accuracy 100% -> weight 100
                raw_weights[sig_type] = accuracy * 100.0
                
        # Normalize weights to sum to 100
        total_raw = sum(raw_weights.values())
        final_weights = {}
        
        for sig, w in raw_weights.items():
            if total_raw > 0:
                final_weights[sig] = (w / total_raw) * 100.0
            else:
                final_weights[sig] = 0.0
                
        return final_weights

    def rebalance_weights_daily(self, asset1: str = "^NSEI", asset2: str = "ES=F", active_signals: List[str] | None = None) -> Dict[str, float]:
        """
        Run at 6 AM IST before signal generation.
        Store weight history in SQLite DynamicWeights.
        """
        if not active_signals:
            active_signals = ["US_LEAD_LAG", "FII_EXHAUSTION", "PCR_EXTREME", "MACRO_REGIME", "WHALE_FLOW"]
            
        corr = self.calculate_rolling_correlation(asset1, asset2, window=30)
        final_weights = self.apply_to_all_signals(corr, active_signals)
        
        # Save to database
        with database_manager.session_scope() as session:
            for sig, weight in final_weights.items():
                existing = session.query(DynamicWeights).filter_by(
                    date=date.today(),
                    signal_type=sig
                ).first()
                
                # Fetch accuracy for logging
                accuracy = 0.0
                # Could re-calculate or just omit; we omitted to save cycles, but let's approximate or just store None
                
                if existing:
                    existing.weight = weight
                    existing.correlation = corr if sig == "US_LEAD_LAG" else None
                else:
                    record = DynamicWeights(
                        date=date.today(),
                        signal_type=sig,
                        weight=weight,
                        correlation=corr if sig == "US_LEAD_LAG" else None,
                        accuracy=None
                    )
                    session.add(record)
                    
        logger.info(f"Dynamic Weights Rebalanced: {final_weights}")
        return final_weights
