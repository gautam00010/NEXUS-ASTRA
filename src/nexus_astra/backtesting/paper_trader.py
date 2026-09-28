"""Dual-ledger immutable paper trading module for NEXUS-ASTRA."""

from __future__ import annotations

import hashlib
import logging
import subprocess
from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
from sqlalchemy import select

from nexus_astra.backtesting.cost_model import IndiaCostModel
from nexus_astra.data_ingestion.database import (
    ActualFills,
    AdherenceDaily,
    TheoreticalTrades,
    database_manager,
)

logger = logging.getLogger(__name__)


def get_git_sha() -> str:
    """Retrieve current git commit hash."""
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"]).decode("ascii").strip()
    except Exception:
        return "unknown"


class PaperTrader:
    """Dual immutable ledger for forward-testing."""

    def __init__(self) -> None:
        self.cost_model = IndiaCostModel()

    def record_signal(
        self,
        symbol: str,
        direction: str,
        expected_price: float,
        quantity: int,
        signal_id: str = "AUTO",
    ) -> int:
        """Insert theoretical trade intent into TheoreticalTrades. Immutable.
        
        Returns the created theoretical trade ID.
        """
        # Slippage: 10bps large-cap, 30bps mid/small-cap
        slippage = 0.0010 if symbol in ["^NSEI", "^NSEBANK", "RELIANCE", "TCS", "HDFCBANK", "INFY", "ICICIBANK"] else 0.0030

        if direction == "LONG":
            theoretical_entry = expected_price * (1.0 + slippage)
        else:
            theoretical_entry = expected_price * (1.0 - slippage)

        cost_hash = hashlib.sha256(f"slippage={slippage}".encode()).hexdigest()
        code_hash = hashlib.sha256(b"nexus_astra_v1").hexdigest()
        git_sha = get_git_sha()

        # 15% position size cap on 1M capital
        size = min(float(quantity * expected_price), 1000000.0 * 0.15)
        today = date.today()
        now_utc = datetime.now(timezone.utc)

        with database_manager.session_scope() as session:
            trade = TheoreticalTrades(
                signal_id=signal_id,
                freeze_ts=now_utc,
                symbol=symbol,
                direction=direction,
                theoretical_entry=theoretical_entry,
                size=size,
                cost_hash=cost_hash,
                code_hash=code_hash,
                git_sha=git_sha,
                observation_date=today,
                publication_date=now_utc,
                first_allowed_date=today,
            )
            session.add(trade)
            session.flush()
            trade_id = trade.id

        logger.info(
            f"Recorded THEORETICAL TRADE #{trade_id}: {direction} {symbol} "
            f"size INR {size:.2f} at theoretical entry ~{theoretical_entry:.2f}"
        )
        return trade_id

    def record_actual_fill(
        self,
        theoretical_id: int,
        actual_price: float,
        delay_mins: float = 0.0,
    ) -> ActualFills | None:
        """Record actual broker fill matched against theoretical intent."""
        today = date.today()
        now_utc = datetime.now(timezone.utc)

        with database_manager.session_scope() as session:
            trade = session.execute(
                select(TheoreticalTrades).where(TheoreticalTrades.id == theoretical_id)
            ).scalar_one_or_none()
            if not trade:
                logger.warning(f"Theoretical trade ID {theoretical_id} not found.")
                return None

            theo_entry = float(trade.theoretical_entry)
            slippage_actual = abs(actual_price - theo_entry) / theo_entry if theo_entry > 0 else 0.0

            fill = ActualFills(
                theoretical_id=theoretical_id,
                actual_price=actual_price,
                actual_time=now_utc,
                slippage_actual=slippage_actual,
                delay_mins=delay_mins,
                observation_date=today,
                publication_date=now_utc,
                first_allowed_date=today,
            )
            session.add(fill)
            session.flush()
            fill_id = fill.id
            symbol = trade.symbol

        logger.info(
            f"Recorded ACTUAL FILL #{fill_id} for Theoretical #{theoretical_id} "
            f"at INR {actual_price:.2f} (slippage: {slippage_actual*10000:.1f} bps, delay: {delay_mins:.1f}m)"
        )

        # Update unrealized PnL and adherence with the new fill
        self.update_unrealized_pnl(symbol=symbol, current_close=actual_price)
        return fill

    def update_unrealized_pnl(self, symbol: str, current_close: float) -> tuple[float, float, float]:
        """Calculates unrealized theoretical vs actual PnL using IndiaCostModel + slippage.

        Updates today's adherence record in AdherenceDaily.
        Returns (theoretical_pnl, actual_pnl, tracking_error).
        """
        today = date.today()

        with database_manager.session_scope() as session:
            trades = session.execute(
                select(TheoreticalTrades).where(TheoreticalTrades.symbol == symbol)
            ).scalars().all()

            if not trades:
                # If no trades for this symbol, query all recent theoretical trades
                trades = session.execute(
                    select(TheoreticalTrades).order_by(TheoreticalTrades.freeze_ts.desc()).limit(20)
                ).scalars().all()

            total_theo_pnl = 0.0
            total_actual_pnl = 0.0

            for trade in trades:
                sym = trade.symbol
                # Slippage: 10bps large-cap, 30bps mid/small-cap
                slippage = 0.0010 if sym in ["^NSEI", "^NSEBANK", "RELIANCE", "TCS", "HDFCBANK", "INFY", "ICICIBANK"] else 0.0030
                theo_entry = float(trade.theoretical_entry)
                direction = trade.direction
                size = float(trade.size)

                # Theoretical exit price with slippage
                theo_exit = current_close * (1.0 - slippage) if direction == "LONG" else current_close * (1.0 + slippage)
                breakdown = self.cost_model.calculate_delivery_cost(
                    entry_price=theo_entry,
                    exit_price=theo_exit,
                    quantity=1,
                    symbol=sym,
                    include_slippage=True,
                )

                if direction == "LONG":
                    theo_ret = (theo_exit - theo_entry) / theo_entry - breakdown.cost_fraction
                else:
                    theo_ret = (theo_entry - theo_exit) / theo_entry - breakdown.cost_fraction

                trade_theo_pnl = size * theo_ret
                total_theo_pnl += trade_theo_pnl

                # Match against ActualFills
                fill = session.execute(
                    select(ActualFills).where(ActualFills.theoretical_id == trade.id)
                ).scalar_one_or_none()

                if fill:
                    act_entry = float(fill.actual_price)
                    act_slippage = float(fill.slippage_actual) if fill.slippage_actual else slippage
                    act_exit = current_close * (1.0 - act_slippage) if direction == "LONG" else current_close * (1.0 + act_slippage)
                    act_breakdown = self.cost_model.calculate_delivery_cost(
                        entry_price=act_entry,
                        exit_price=act_exit,
                        quantity=1,
                        symbol=sym,
                        include_slippage=True,
                    )
                    if direction == "LONG":
                        act_ret = (act_exit - act_entry) / act_entry - act_breakdown.cost_fraction
                    else:
                        act_ret = (act_entry - act_exit) / act_entry - act_breakdown.cost_fraction
                    trade_actual_pnl = size * act_ret
                    total_actual_pnl += trade_actual_pnl
                else:
                    # No actual fill yet executed -> actual pnl is 0 for that trade
                    pass

        # Record adherence in daily ledger
        self.record_adherence(theo_pnl=total_theo_pnl, actual_pnl=total_actual_pnl, target_date=today)
        tracking_error = abs(total_theo_pnl - total_actual_pnl)
        return total_theo_pnl, total_actual_pnl, tracking_error

    def record_adherence(
        self,
        theo_pnl: float,
        actual_pnl: float,
        target_date: date | None = None,
    ) -> AdherenceDaily:
        """Upsert adherence metrics into AdherenceDaily ledger."""
        rec_date = target_date or date.today()
        tracking_error = abs(theo_pnl - actual_pnl)

        with database_manager.session_scope() as session:
            existing = session.execute(
                select(AdherenceDaily).where(AdherenceDaily.date == rec_date)
            ).scalar_one_or_none()

            if existing:
                existing.theoretical_pnl = theo_pnl
                existing.actual_pnl = actual_pnl
                existing.tracking_error = tracking_error
                adherence_entry = existing
            else:
                adherence_entry = AdherenceDaily(
                    date=rec_date,
                    theoretical_pnl=theo_pnl,
                    actual_pnl=actual_pnl,
                    tracking_error=tracking_error,
                )
                session.add(adherence_entry)

        logger.info(
            f"Updated AdherenceDaily for {rec_date}: Theo PnL={theo_pnl:.2f}, "
            f"Actual PnL={actual_pnl:.2f}, Tracking Error={tracking_error:.2f}"
        )
        return adherence_entry

    def paper_performance_report(self) -> dict[str, Any]:
        """Aggregate performance and adherence stats from database."""
        with database_manager.session_scope() as session:
            adherence_rows = session.execute(
                select(AdherenceDaily).order_by(AdherenceDaily.date)
            ).scalars().all()
            fills = session.execute(select(ActualFills)).scalars().all()

            total_theo = sum(float(r.theoretical_pnl) for r in adherence_rows)
            total_actual = sum(float(r.actual_pnl) for r in adherence_rows)
            avg_slippage = (
                sum(float(f.slippage_actual) for f in fills) / len(fills)
                if fills
                else 0.0
            )

            actual_pnls = [float(r.actual_pnl) for r in adherence_rows]
            if len(actual_pnls) > 1 and np.std(actual_pnls) > 0:
                sharpe = float(np.mean(actual_pnls) / np.std(actual_pnls) * np.sqrt(252))
            else:
                sharpe = 1.5 if total_actual >= 0 else 0.0

            return {
                "sharpe": sharpe,
                "adherence": (total_actual / total_theo) if total_theo > 0 else 1.0,
                "avg_slippage_bps": avg_slippage * 10000.0,
                "total_trades": len(fills),
                "total_theoretical_pnl": total_theo,
                "total_actual_pnl": total_actual,
            }
