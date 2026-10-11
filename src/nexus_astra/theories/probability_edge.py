"""Mathematical Probability Edge & The Law of Large Numbers in Quantitative Trading.

Fundamental Axiom:
- Trading is NOT predicting where the next candle goes.
- Trading is capturing a positive mathematical expectancy distribution over 200+ independent trials.
- Even a 51% win rate with an asymmetric 1:2 risk-to-reward ratio yields an overwhelming edge:
    Expectancy = (Win% * AvgWin) - (Loss% * AvgLoss)
    E = (0.51 * 2.0R) - (0.49 * 1.0R) = 1.02 - 0.49 = +0.53R per trade!
- Over 200 trades risking 1% capital:
    Net Gain ≈ 200 * 0.53% = +106% capital appreciation before compounding.
"""

from __future__ import annotations
import logging
from typing import Any, Dict
import numpy as np

logger = logging.getLogger(__name__)


def calculate_expectancy(
    win_rate: float = 0.51,
    avg_win_r: float = 2.0,
    avg_loss_r: float = 1.0,
) -> Dict[str, Any]:
    """
    Computes mathematical expectancy per trade in units of R (risk).

    Formula:
      E = (Win_Rate * Avg_Win) - (Loss_Rate * Avg_Loss)
    """
    loss_rate = 1.0 - win_rate
    expectancy_r = (win_rate * avg_win_r) - (loss_rate * avg_loss_r)
    is_positive = expectancy_r > 0

    return {
        "win_rate_pct": round(win_rate * 100.0, 1),
        "loss_rate_pct": round(loss_rate * 100.0, 1),
        "risk_reward_ratio": f"1:{avg_win_r / avg_loss_r:.1f}",
        "avg_win_r": avg_win_r,
        "avg_loss_r": avg_loss_r,
        "expectancy_r_per_trade": round(expectancy_r, 4),
        "is_positive_edge": is_positive,
        "law_of_large_numbers_insight": (
            f"Over 200 executions, expected cumulative return is +{expectancy_r * 200:.1f}R. "
            "Individual trade outcomes are random noise; the 200-trade distribution is an iron mathematical law."
        ),
    }


def simulate_equity_curve(
    win_rate: float = 0.51,
    avg_win_r: float = 2.0,
    avg_loss_r: float = 1.0,
    num_trades: int = 200,
    initial_capital: float = 100_000.0,
    risk_per_trade_pct: float = 0.01,
    seed: int = 42,
) -> Dict[str, Any]:
    """
    Simulates a 200-trade equity path using Monte Carlo under the Law of Large Numbers.
    """
    np.random.seed(seed)
    outcomes = np.random.random(num_trades) < win_rate
    trade_r_multiples = np.where(outcomes, avg_win_r, -avg_loss_r)

    equity = [initial_capital]
    for r in trade_r_multiples:
        risk_amount = equity[-1] * risk_per_trade_pct
        pnl = risk_amount * r
        equity.append(max(0.0, equity[-1] + pnl))

    equity_arr = np.array(equity)
    peaks = np.maximum.accumulate(equity_arr)
    drawdowns = (peaks - equity_arr) / peaks
    max_dd = float(np.max(drawdowns)) * 100.0
    total_return_pct = float((equity_arr[-1] / initial_capital) - 1.0) * 100.0

    return {
        "initial_capital": initial_capital,
        "final_capital": round(float(equity_arr[-1]), 2),
        "total_return_pct": round(total_return_pct, 2),
        "max_drawdown_pct": round(max_dd, 2),
        "trades_executed": num_trades,
        "actual_win_rate_pct": round(float(np.mean(outcomes) * 100.0), 1),
        "expectancy_r": round(float(np.mean(trade_r_multiples)), 4),
    }
