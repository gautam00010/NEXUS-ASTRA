"""Survivorship Bias Engine for true point-in-time backtesting."""

from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Dict, List, Any

import numpy as np
import polars as pl
from dataclasses import asdict, is_dataclass

from nexus_astra.data_ingestion.database import IndexConstituents, database_manager

logger = logging.getLogger(__name__)


class SurvivorshipCorrector:
    """Manages point-in-time constituent filtering and delisting penalties."""

    def __init__(self) -> None:
        self.penalty_pct = 0.15 # 15% penalty for holding through delisting
        self._constituents_cache: pl.DataFrame | None = None

    def _load_constituents_df(self) -> pl.DataFrame:
        if self._constituents_cache is not None and not self._constituents_cache.is_empty():
            return self._constituents_cache
            
        with database_manager.session_scope() as session:
            rows = session.query(IndexConstituents).all()
            
        if not rows:
            df = pl.DataFrame(schema={
                "index_name": pl.Utf8,
                "symbol": pl.Utf8,
                "entry_date": pl.Date,
                "exit_date": pl.Date,
                "is_delisted": pl.Boolean
            })
            self._constituents_cache = df
            return df
            
        records: list[dict[str, Any]] = []
        for row in rows:
            record = asdict(row) if is_dataclass(row) else row.__dict__.copy()
            record.pop("_sa_instance_state", None)
            records.append(record)
            
        df = pl.DataFrame(records)
        self._constituents_cache = df
        return df

    def load_historical_constituents(self, df: pl.DataFrame) -> None:
        """
        Load monthly Nifty 50/500 constituents 2010-present.
        Expects Polars df with: index_name, symbol, entry_date, exit_date, is_delisted.
        """
        with database_manager.session_scope() as session:
            for row in df.to_dicts():
                record = IndexConstituents(
                    index_name=row["index_name"],
                    symbol=row["symbol"],
                    entry_date=row["entry_date"],
                    exit_date=row.get("exit_date"),
                    is_delisted=row.get("is_delisted", False)
                )
                session.add(record)
                
        # Invalidate cache
        self._constituents_cache = None
        logger.info(f"Loaded {len(df)} historical constituents into database.")

    def apply_delisted_penalty(
        self,
        signal_date: date,
        symbol: str,
        raw_return: float,
        recovery_pct: float = 0.0,
    ) -> float | str:
        """
        If a stock was delisted, apply actual delisted return = -100% after delisting date + recovery if any.
        If constituents table is empty, returns 'DATA_FAIL' (never a synthetic adjustment).
        """
        df = self._load_constituents_df()
        if df.is_empty():
            logger.error("DATA_FAIL: IndexConstituents table is empty.")
            return "DATA_FAIL"
            
        # Check if this symbol was marked as delisted
        symbol_data = df.filter(
            (pl.col("symbol") == symbol) & 
            (pl.col("is_delisted") == True)
        )
        
        if symbol_data.is_empty():
            return raw_return
            
        # Check if the signal date falls on or after exit_date (delisting date),
        # or if the holding window (up to 2 years) crosses the delisting date
        two_years_later = signal_date + timedelta(days=365 * 2)
        delisted_records = symbol_data.filter(
            (pl.col("exit_date").is_not_null()) &
            ((pl.col("exit_date") <= signal_date) | 
             ((pl.col("exit_date") >= signal_date) & (pl.col("exit_date") <= two_years_later)))
        )
        
        if not delisted_records.is_empty():
            # Actual delisted return is -100% (-1.0) plus any recovery
            actual_delisted_return = (-100.0 + recovery_pct * 100.0) if abs(raw_return) > 1.0 else (-1.0 + recovery_pct)
            logger.warning(
                f"Delisted asset {symbol} held through/after delisting on {signal_date}. "
                f"Applied actual delisted return: {actual_delisted_return:.2%}"
            )
            return actual_delisted_return
            
        return raw_return

    def point_in_time_filter(self, signal_date: date, index_name: str = "NIFTY_50") -> List[str]:
        """
        When backtesting a signal dated X, only use stocks that were IN the index ON that exact date.
        If constituents table is empty, logs DATA_FAIL and returns empty list.
        """
        df = self._load_constituents_df()
        if df.is_empty():
            logger.error("DATA_FAIL: IndexConstituents table is empty.")
            return []
            
        # A stock is IN the index if entry_date <= signal_date AND (exit_date IS NULL OR exit_date > signal_date)
        active_symbols = df.filter(
            (pl.col("index_name") == index_name) &
            (pl.col("entry_date") <= signal_date) &
            (pl.col("exit_date").is_null() | (pl.col("exit_date") > signal_date))
        )
        
        return active_symbols.get_column("symbol").unique().to_list()

    def bias_report(self, original_returns: List[float], adjusted_returns: List[float]) -> str:
        """
        After each backtest run, report: 
        'Survivorship bias penalty applied to X% of signals. Adjusted Sharpe: X vs Unadjusted Sharpe: Y.'
        """
        if not original_returns or not adjusted_returns or len(original_returns) != len(adjusted_returns):
            return "Invalid return sequences provided for bias report."
            
        total_signals = len(original_returns)
        penalized_count = sum(1 for orig, adj in zip(original_returns, adjusted_returns) if adj < orig)
        
        penalty_pct = (penalized_count / total_signals) * 100.0 if total_signals > 0 else 0.0
        
        orig_arr = np.array(original_returns)
        adj_arr = np.array(adjusted_returns)
        
        # Simple Sharpe calculation (assuming daily returns, annualized by sqrt(252))
        def calc_sharpe(returns: np.ndarray) -> float:
            if len(returns) < 2 or np.std(returns) == 0:
                return 0.0
            return (np.mean(returns) / np.std(returns)) * np.sqrt(252)
            
        unadjusted_sharpe = calc_sharpe(orig_arr)
        adjusted_sharpe = calc_sharpe(adj_arr)
        
        report = (
            f"Survivorship bias penalty applied to {penalty_pct:.1f}% of signals. "
            f"Adjusted Sharpe: {adjusted_sharpe:.2f} vs Unadjusted Sharpe: {unadjusted_sharpe:.2f}."
        )
        
        logger.info(report)
        return report
