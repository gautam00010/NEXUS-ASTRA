"""Bayesian confidence updating for real-time signal modifications."""

from __future__ import annotations

import logging
from dataclasses import asdict, is_dataclass
from datetime import datetime
from typing import Any, Dict, List

import numpy as np
import polars as pl
import asyncio

from nexus_astra.data_ingestion.database import BayesianPriors, ActiveSignalState, database_manager
from nexus_astra.delivery.telegram_delivery import send_telegram_signal

logger = logging.getLogger(__name__)


class BayesianConfidence:
    """Real-time Bayesian updates for active trading signals."""

    def __init__(self) -> None:
        pass

    def update_confidence(self, prior: float, likelihood: float, evidence: float) -> float:
        """
        Calculate Posterior = (Prior * Likelihood) / Evidence.
        prior is assumed to be a probability between 0.0 and 1.0 (composite score / 100).
        """
        if evidence == 0.0:
            return prior
            
        posterior = (prior * likelihood) / evidence
        return min(max(posterior, 0.0), 1.0)

    def build_likelihood_table(self, historical_data: pl.DataFrame) -> None:
        """
        From historical data, build lookup tables:
        P(data_feature | signal_correct).
        historical_data should contain: signal_type, data_feature, feature_state, signal_correct (bool).
        """
        if historical_data.is_empty():
            return
            
        # P(data) = marginal probability
        total_rows = len(historical_data)
        
        # We need P(feature_state | signal_type, signal_correct==True)
        correct_signals = historical_data.filter(pl.col("signal_correct") == True)
        
        with database_manager.session_scope() as session:
            # We group by signal_type, data_feature, feature_state
            for signal_type in historical_data.get_column("signal_type").unique().to_list():
                for feature in historical_data.get_column("data_feature").unique().to_list():
                    for state in historical_data.get_column("feature_state").unique().to_list():
                        
                        # Marginal P(data)
                        count_data = len(historical_data.filter(
                            (pl.col("data_feature") == feature) &
                            (pl.col("feature_state") == state)
                        ))
                        evidence = count_data / total_rows if total_rows > 0 else 0.0
                        
                        # Likelihood P(data | signal_correct)
                        correct_subset = correct_signals.filter(
                            pl.col("signal_type") == signal_type
                        )
                        count_correct = len(correct_subset)
                        
                        if count_correct == 0:
                            likelihood = 0.0
                        else:
                            count_feature_given_correct = len(correct_subset.filter(
                                (pl.col("data_feature") == feature) &
                                (pl.col("feature_state") == state)
                            ))
                            likelihood = count_feature_given_correct / count_correct
                            
                        # Store in SQLite
                        existing = session.query(BayesianPriors).filter_by(
                            signal_type=signal_type,
                            data_feature=feature,
                            feature_state=state
                        ).first()
                        
                        if existing:
                            existing.likelihood = likelihood
                            existing.marginal_prob = evidence
                        else:
                            prior_record = BayesianPriors(
                                signal_type=signal_type,
                                data_feature=feature,
                                feature_state=state,
                                likelihood=likelihood,
                                marginal_prob=evidence
                            )
                            session.add(prior_record)

    async def real_time_update(self, signal_id: str, data_feature: str, feature_state: str) -> None:
        """
        When new data arrives, fetch the signal, apply Bayesian update, 
        and push revised confidence to Telegram if it crosses thresholds.
        """
        with database_manager.session_scope() as session:
            signal_state = session.query(ActiveSignalState).filter_by(
                signal_id=signal_id, 
                status="ACTIVE"
            ).first()
            
            if not signal_state:
                return
                
            prior = float(signal_state.current_confidence) / 100.0
            
            # Look up priors
            prior_record = session.query(BayesianPriors).filter_by(
                signal_type=signal_state.signal_type,
                data_feature=data_feature,
                feature_state=feature_state
            ).first()
            
            if not prior_record:
                # No historical data for this combination
                return
                
            likelihood = float(prior_record.likelihood)
            evidence = float(prior_record.marginal_prob)
            
            posterior = self.update_confidence(prior, likelihood, evidence)
            new_confidence = posterior * 100.0
            
            # Update the database
            signal_state.current_confidence = new_confidence
            
            # Threshold checks
            msg = None
            if new_confidence >= 90.0:
                msg = f"HIGH CONFIDENCE UPGRADE: Signal {signal_id} ({signal_state.symbol}) jumped to {new_confidence:.1f}% due to {data_feature}={feature_state}."
            elif new_confidence <= 60.0:
                signal_state.status = "CANCELLED"
                msg = f"SIGNAL CANCELLED: Signal {signal_id} ({signal_state.symbol}) confidence collapsed to {new_confidence:.1f}% due to {data_feature}={feature_state}. Exiting."
                
            if msg:
                logger.info(msg)
                payload = {
                    "Type": "Bayesian Update",
                    "Signal ID": signal_id,
                    "Symbol": signal_state.symbol,
                    "New Confidence": f"{new_confidence:.1f}%",
                    "Reason": f"{data_feature}={feature_state}",
                    "Action": "CANCEL/EXIT" if new_confidence <= 60.0 else "INCREASE SIZE"
                }
                try:
                    await send_telegram_signal(payload)
                except Exception as e:
                    logger.error(f"Failed to send Bayesian Telegram alert: {e}")

    def entropy_check(self) -> str | None:
        """
        Calculate Shannon entropy H = -sum(p_i * log2(p_i)) across all active signals.
        If H > 2.0, flag MIXED_SIGNALS_REDUCE_SIZE.
        """
        with database_manager.session_scope() as session:
            active_signals = session.query(ActiveSignalState).filter_by(status="ACTIVE").all()
            
        if not active_signals:
            return None
            
        confidences = [float(s.current_confidence) for s in active_signals]
        
        # Normalize to create a probability distribution
        total_conf = sum(confidences)
        if total_conf == 0:
            return None
            
        probs = np.array(confidences) / total_conf
        
        # Calculate Shannon Entropy
        entropy = -np.sum(probs * np.log2(probs + 1e-9))
        
        if entropy > 2.0:
            logger.warning(f"System Entropy high (H={entropy:.2f}). Flagging MIXED_SIGNALS_REDUCE_SIZE.")
            return "MIXED_SIGNALS_REDUCE_SIZE"
            
        return None
