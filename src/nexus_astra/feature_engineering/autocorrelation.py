"""Autocorrelation monitor to detect and penalize redundant or overlapping signals."""

from __future__ import annotations

import logging
from datetime import date
from typing import Dict, List, Tuple, Any

import numpy as np
import polars as pl
from scipy import stats

from nexus_astra.data_ingestion.database import SignalDiagnostics, database_manager

logger = logging.getLogger(__name__)


class AutocorrelationMonitor:
    """Monitors signal series for autocorrelation and cross-correlation."""

    def __init__(self) -> None:
        pass

    def durbin_watson_test(self, series: np.ndarray | List[float]) -> float:
        """
        Calculate DW = sum((e_t - e_{t-1})^2) / sum(e_t^2)
        DW < 1.5 = high positive autocorrelation
        DW > 2.5 = high negative autocorrelation
        """
        arr = np.asarray(series, dtype=float)
        if len(arr) < 2:
            return 2.0 # Default to neutral
            
        diffs = np.diff(arr)
        dw = np.sum(diffs**2) / np.sum(arr**2)
        
        # Guard against zero division
        if np.isnan(dw) or np.isinf(dw):
            return 2.0
            
        return float(dw)

    def get_autocorrelation(self, series: np.ndarray, lag: int = 1) -> float:
        """Calculate Pearson autocorrelation coefficient at a specific lag."""
        if len(series) <= lag:
            return 0.0
        r, _ = stats.pearsonr(series[lag:], series[:-lag])
        return float(r)

    def decorrelate_signal(self, series: np.ndarray | List[float], lag: int = 1) -> np.ndarray:
        """
        If autocorrelated, transform: signal_t - rho * signal_{t-1}.
        This removes the predictable component.
        """
        arr = np.asarray(series, dtype=float)
        if len(arr) <= lag:
            return arr
            
        rho = self.get_autocorrelation(arr, lag=lag)
        
        decorrelated = np.zeros_like(arr)
        # The first `lag` elements remain unchanged or we can scale them.
        # Standard quasi-differencing:
        decorrelated[:lag] = arr[:lag] * np.sqrt(1 - rho**2)
        decorrelated[lag:] = arr[lag:] - rho * arr[:-lag]
        return decorrelated

    def signal_independence_test(self, signals_dict: Dict[str, List[float]]) -> List[Tuple[str, str, float]]:
        """
        Calculate cross-correlation at lag 0 for every pair of signals.
        If |r| > 0.7, flag REDUNDANT_SIGNAL.
        """
        keys = list(signals_dict.keys())
        redundant_pairs = []
        
        for i in range(len(keys)):
            for j in range(i + 1, len(keys)):
                sig1 = keys[i]
                sig2 = keys[j]
                
                arr1 = np.asarray(signals_dict[sig1], dtype=float)
                arr2 = np.asarray(signals_dict[sig2], dtype=float)
                
                # Truncate to the minimum length to align properly
                min_len = min(len(arr1), len(arr2))
                if min_len < 2:
                    continue
                    
                arr1 = arr1[-min_len:]
                arr2 = arr2[-min_len:]
                
                r, _ = stats.pearsonr(arr1, arr2)
                
                if abs(r) > 0.7:
                    logger.warning(f"REDUNDANT_SIGNAL: {sig1} and {sig2} are highly correlated (|r|={abs(r):.2f}).")
                    redundant_pairs.append((sig1, sig2, r))
                    
        return redundant_pairs

    def effective_sample_size(self, series: np.ndarray | List[float]) -> float:
        """
        N_effective = N / (1 + 2 * sum(rho_k)).
        Report true degrees of freedom for statistical tests.
        """
        arr = np.asarray(series, dtype=float)
        n = len(arr)
        if n < 3:
            return float(n)
            
        rho_sum = 0.0
        # Calculate lag up to N/4 or max 10
        max_lag = min(10, n // 4)
        if max_lag < 1:
            return float(n)
        
        # Calculate autocorrelations using list comprehension and NumPy array filtering
        rhos = np.array([self.get_autocorrelation(arr, lag=k) for k in range(1, max_lag + 1)])
        rho_sum = float(np.sum(rhos[np.abs(rhos) > 0.05]))
                
        denominator = 1.0 + 2.0 * rho_sum
        if denominator <= 0:
            return 1.0
            
        n_effective = n / denominator
        return float(min(n_effective, n)) # Effective size cannot be greater than actual size (typically)

    def run_weekly_diagnostics(self, signals_dict: Dict[str, List[float]]) -> None:
        """
        Run weekly checks. Calculate DW, independence, and effective sample size.
        Store in SQLite SignalDiagnostics. Use scipy.stats + Polars.
        """
        today = date.today()
        
        with database_manager.session_scope() as session:
            # 1. Durbin Watson and Effective Sample Size
            for sig_name, series in signals_dict.items():
                if len(series) < 2:
                    continue
                    
                dw = self.durbin_watson_test(series)
                n_eff = self.effective_sample_size(series)
                
                # Store DW
                session.add(SignalDiagnostics(
                    date=today,
                    diagnostic_type="DURBIN_WATSON",
                    signal_type=sig_name,
                    metric_value=dw,
                    details="High positive" if dw < 1.5 else ("High negative" if dw > 2.5 else "Neutral")
                ))
                
                # Store N_eff
                session.add(SignalDiagnostics(
                    date=today,
                    diagnostic_type="EFFECTIVE_SAMPLE_SIZE",
                    signal_type=sig_name,
                    metric_value=n_eff,
                    details=f"Raw N: {len(series)}"
                ))
                
            # 2. Cross-correlation (Independence Test)
            redundancies = self.signal_independence_test(signals_dict)
            for sig1, sig2, r in redundancies:
                session.add(SignalDiagnostics(
                    date=today,
                    diagnostic_type="REDUNDANT_SIGNAL",
                    signal_type=f"{sig1}|{sig2}",
                    metric_value=r,
                    details=f"Absolute correlation |r|={abs(r):.2f} > 0.7 threshold."
                ))
                
        logger.info("Completed weekly autocorrelation and redundancy diagnostics.")
