"""Base Rate Engine for preventing low base-rate traps in signal execution."""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from typing import Dict, Any

import polars as pl
from dataclasses import asdict, is_dataclass

from nexus_astra.data_ingestion.database import BaseRateAnalytics, DailyPriceData, database_manager

logger = logging.getLogger(__name__)


class BaseRateMonitor:
    """Monitors Base Rates and PPV to gate low-probability alerts."""

    def __init__(self) -> None:
        pass

    def calculate_base_rate(self, symbol: str, duration_days: int, target_pct_move: float, lookback_years: int = 5) -> float:
        """
        Historical prevalence of the predicted move occurring within expected duration unconditionally.
        E.g., 'Nifty +3% in 5 days' -> look at all rolling 5-day periods in last 5 years.
        """
        cutoff_date = date.today() - timedelta(days=lookback_years * 365)
        
        with database_manager.session_scope() as session:
            rows = session.query(DailyPriceData).filter(
                DailyPriceData.symbol == symbol,
                DailyPriceData.trade_date >= cutoff_date
            ).order_by(DailyPriceData.trade_date.asc()).all()
            
        if not rows:
            return 0.0
            
        records: list[dict[str, Any]] = []
        for row in rows:
            record = asdict(row) if is_dataclass(row) else row.__dict__.copy()
            record.pop("_sa_instance_state", None)
            records.append(record)
            
        df = pl.DataFrame(records)
        if len(df) <= duration_days:
            return 0.0
            
        # Calculate N-day forward returns
        # shift(-N) brings the future price back to current row
        df = df.with_columns(
            (pl.col("close").shift(-duration_days) / pl.col("close") - 1.0).alias("forward_return")
        )
        
        # Drop the last N days where forward_return is null
        df = df.drop_nulls(subset=["forward_return"])
        total_periods = len(df)
        if total_periods == 0:
            return 0.0
            
        if target_pct_move > 0:
            occurrences = len(df.filter(pl.col("forward_return") >= target_pct_move))
        else:
            occurrences = len(df.filter(pl.col("forward_return") <= target_pct_move))
            
        base_rate = occurrences / total_periods
        return base_rate

    def calculate_ppv(self, base_rate: float, sensitivity: float, specificity: float) -> float:
        """
        Calculate Positive Predictive Value using Bayes formula.
        PPV = (Sensitivity * BaseRate) / [(Sensitivity * BaseRate) + ((1 - Specificity) * (1 - BaseRate))]
        """
        numerator = sensitivity * base_rate
        denominator = numerator + ((1.0 - specificity) * (1.0 - base_rate))
        
        if denominator == 0:
            return 0.0
        return numerator / denominator

    def ppv_threshold_gate(self, signal_type: str, ppv: float) -> bool:
        """
        Before emitting any alert, check PPV. 
        If PPV < 40%, suppress alert.
        """
        if ppv < 0.40:
            logger.warning(f"LOW_BASE_RATE_SUPPRESSION: {signal_type} suppressed. PPV {ppv:.2%} < 40%.")
            return False
        return True

    def rare_event_warning(self, base_rate: float, ppv: float, composite_confidence: float) -> bool:
        """
        If base rate < 5% (very rare event), require PPV > 60% AND composite confidence > 90 to emit.
        Returns True if it's safe to emit, False if suppressed due to rarity.
        """
        if base_rate < 0.05:
            if ppv > 0.60 and composite_confidence > 90.0:
                logger.info(f"Rare event approved: BR={base_rate:.2%}, PPV={ppv:.2%}, Conf={composite_confidence}")
                return True
            else:
                logger.warning(f"RARE_EVENT_SUPPRESSION: BR={base_rate:.2%} requires PPV>60% & Conf>90. Got PPV={ppv:.2%}, Conf={composite_confidence}")
                return False
        return True

    def update_analytics(self, date_val: date, signal_type: str, base_rate: float, sensitivity: float, specificity: float) -> float:
        """
        Store in SQLite BaseRateAnalytics. Update monthly (or whenever triggered).
        """
        ppv = self.calculate_ppv(base_rate, sensitivity, specificity)
        
        with database_manager.session_scope() as session:
            existing = session.query(BaseRateAnalytics).filter_by(
                date=date_val,
                signal_type=signal_type
            ).first()
            
            if existing:
                existing.base_rate = base_rate
                existing.sensitivity = sensitivity
                existing.specificity = specificity
                existing.ppv = ppv
            else:
                record = BaseRateAnalytics(
                    date=date_val,
                    signal_type=signal_type,
                    base_rate=base_rate,
                    sensitivity=sensitivity,
                    specificity=specificity,
                    ppv=ppv
                )
                session.add(record)
                
        return ppv
