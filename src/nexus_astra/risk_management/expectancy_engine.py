"""Expectancy Engine: Trade log tracking and expectancy calculations."""

from __future__ import annotations

import logging
from dataclasses import asdict, is_dataclass
from typing import Any, Dict, List
import datetime

import numpy as np
import polars as pl

from nexus_astra.data_ingestion.database import TradeLog, database_manager

logger = logging.getLogger(__name__)


class ExpectancyTracker:
    """Tracks trade expectancy, geometric mean, and PPV across regimes."""

    def __init__(self) -> None:
        pass

    def log_closed_trade(self, symbol: str, signal_type: str, regime: str, entry_date: datetime.date, exit_date: datetime.date, pnl_pct: float) -> None:
        """Log a closed trade into the TradeLog table."""
        with database_manager.session_scope() as session:
            trade = TradeLog(
                symbol=symbol,
                signal_type=signal_type,
                regime=regime,
                entry_date=entry_date,
                exit_date=exit_date,
                pnl_pct=pnl_pct
            )
            session.add(trade)
            
    def _load_trade_log(self) -> pl.DataFrame:
        """Load the entire TradeLog as a Polars DataFrame."""
        with database_manager.session_scope() as session:
            rows = session.query(TradeLog).all()
            
        if not rows:
            return pl.DataFrame()
            
        records: list[dict[str, Any]] = []
        for row in rows:
            record = asdict(row) if is_dataclass(row) else row.__dict__.copy()
            record.pop("_sa_instance_state", None)
            records.append(record)
            
        df = pl.DataFrame(records)
        return df

    def calculate_expectancy(self, df: pl.DataFrame | None = None) -> float:
        """Calculate arithmetic expectancy: (WinRate × AvgWin) - (LossRate × AvgLoss)."""
        if df is None:
            df = self._load_trade_log()
            
        if df.is_empty():
            return 0.0
            
        total_trades = len(df)
        if total_trades == 0:
            return 0.0
            
        winning_trades = df.filter(pl.col("pnl_pct") > 0)
        losing_trades = df.filter(pl.col("pnl_pct") <= 0)
        
        win_rate = len(winning_trades) / total_trades
        loss_rate = len(losing_trades) / total_trades
        
        avg_win = float(winning_trades.select(pl.col("pnl_pct").mean()).item()) if not winning_trades.is_empty() else 0.0
        avg_loss = float(losing_trades.select(pl.col("pnl_pct").mean()).item()) if not losing_trades.is_empty() else 0.0
        avg_loss = abs(avg_loss) # Average loss should be magnitude
        
        return (win_rate * avg_win) - (loss_rate * avg_loss)

    def calculate_geometric_mean(self, df: pl.DataFrame | None = None) -> float:
        """Calculate geometric mean: [(1+r1)(1+r2)...(1+rn)]^(1/n) - 1."""
        if df is None:
            df = self._load_trade_log()
            
        if df.is_empty():
            return 0.0
            
        n = len(df)
        if n == 0:
            return 0.0
            
        # (1 + r_i) where r_i is pnl_pct (e.g., 0.05 for 5%)
        # Note: If there's a total wipeout (r <= -1), clip to small positive to avoid math errors
        returns_plus_one = df.select(
            pl.when(pl.col("pnl_pct") <= -1.0)
            .then(0.0001)
            .otherwise(1.0 + pl.col("pnl_pct"))
            .alias("pnl_pct")
        )
        
        # We can use exp(mean(log(1+r))) to avoid overflow/underflow
        log_returns = returns_plus_one.select(pl.col("pnl_pct").log())
        mean_log = float(log_returns.mean().item())
        geom_mean = np.exp(mean_log) - 1.0
        
        return float(geom_mean)

    def calculate_ppv(self, base_rate: float, sensitivity: float, specificity: float) -> float:
        """
        Calculate Positive Predictive Value using Bayes formula.
        PPV = (Sensitivity * Base Rate) / ((Sensitivity * Base Rate) + ((1 - Specificity) * (1 - Base Rate)))
        """
        numerator = sensitivity * base_rate
        denominator = numerator + ((1.0 - specificity) * (1.0 - base_rate))
        
        if denominator == 0:
            return 0.0
        return numerator / denominator

    def calculate_base_rates(self, df: pl.DataFrame | None = None) -> Dict[str, float]:
        """Calculate historical win rate (base rate) for each signal type."""
        if df is None:
            df = self._load_trade_log()
            
        if df.is_empty():
            return {}
            
        # Group by signal_type and compute win rate
        base_rates_df = df.group_by("signal_type").agg(
            ((pl.col("pnl_pct") > 0).sum() / pl.count()).alias("base_rate")
        )
        
        rates = {}
        for row in base_rates_df.to_dicts():
            rates[row["signal_type"]] = row["base_rate"]
        return rates

    def regime_significance_test(self, df: pl.DataFrame | None = None) -> bool:
        """
        Remove each regime period (bull/bear/crisis) from history. 
        If removing any single regime changes win rate by >10 percentage points, 
        flag INSUFFICIENT_SAMPLE_SIZE.
        Returns True if test passes (robust), False if it fails (dependent).
        """
        if df is None:
            df = self._load_trade_log()
            
        if df.is_empty():
            return False
            
        total_trades = len(df)
        if total_trades == 0:
            return False
            
        overall_win_rate = len(df.filter(pl.col("pnl_pct") > 0)) / total_trades
        
        regimes = df.get_column("regime").unique().to_list()
        
        for regime in regimes:
            df_excluded = df.filter(pl.col("regime") != regime)
            excluded_trades = len(df_excluded)
            
            if excluded_trades == 0:
                continue
                
            excluded_win_rate = len(df_excluded.filter(pl.col("pnl_pct") > 0)) / excluded_trades
            
            if abs(overall_win_rate - excluded_win_rate) > 0.10:
                logger.warning(f"Regime Significance Test failed: Removing {regime} changes win rate by >10%.")
                return False
                
        return True

    def get_dashboard(self, sensitivity_assumptions: Dict[str, float] | None = None, specificity_assumptions: Dict[str, float] | None = None) -> Dict[str, Any]:
        """Return daily updated dashboard dict."""
        df = self._load_trade_log()
        
        if df.is_empty():
            return {"status": "NO_TRADES"}
            
        expectancy = self.calculate_expectancy(df)
        geom_mean = self.calculate_geometric_mean(df)
        
        capital_destroying = geom_mean < 0
        
        base_rates = self.calculate_base_rates(df)
        
        ppv_results = {}
        sens = sensitivity_assumptions or {}
        spec = specificity_assumptions or {}
        
        for signal_type, br in base_rates.items():
            s = sens.get(signal_type, 0.6) # Default 60% sensitivity
            sp = spec.get(signal_type, 0.5) # Default 50% specificity
            ppv_results[signal_type] = self.calculate_ppv(br, s, sp)
            
        regime_robust = self.regime_significance_test(df)
        
        flags = []
        if capital_destroying:
            flags.append("CAPITAL_DESTROYING_ALERT")
        if not regime_robust:
            flags.append("INSUFFICIENT_SAMPLE_SIZE")
            
        return {
            "status": "OK",
            "total_trades": len(df),
            "expectancy": expectancy,
            "geometric_mean": geom_mean,
            "capital_destroying": capital_destroying,
            "ppv_by_signal": ppv_results,
            "regime_robust": regime_robust,
            "flags": flags
        }
