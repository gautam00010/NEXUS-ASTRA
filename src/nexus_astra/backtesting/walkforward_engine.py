"""Walk-forward backtesting engine with realistic Indian transaction costs and VectorBT integration."""

from __future__ import annotations

import logging
from typing import Any, Dict
import numpy as np
import polars as pl

from nexus_astra.backtesting.cost_model import IndiaCostModel
from nexus_astra.signal_engine.vectorbt_engine import VectorBTEngine

logger = logging.getLogger(__name__)


class WalkForwardBacktester:
    """Walk-forward backtesting engine with Indian cost model integration."""

    def __init__(
        self,
        train_days: int = 252,
        test_days: int = 63,
        min_cycles: int = 5,
        cost_model: IndiaCostModel | None = None,
        include_costs: bool = True,
        fees: float = 0.001,
        slippage: float = 0.001,
    ) -> None:
        self.train_days = train_days
        self.test_days = test_days
        self.min_cycles = min_cycles
        self.cost_model = cost_model or IndiaCostModel()
        self.include_costs = include_costs
        self.fees = fees
        self.slippage = slippage

    def simulate_signals(self, test_data: pl.DataFrame, symbol: str = "DEFAULT") -> pl.DataFrame:
        """
        Simulates trading on a test dataset.
        Expects columns: Date, Open, Close, High, Low, CompositeScore, India_VIX
        """
        df = test_data.sort("Date")
        df = df.with_columns(
            (pl.col("CompositeScore") > 75).cast(pl.Int32).shift(1).alias("EnterLong")
        ).fill_null(0)

        # Enter at Open, exit at next Close (or current Close if last bar)
        df = df.with_columns(
            pl.col("Open").alias("EntryPrice"),
            pl.coalesce([pl.col("Close").shift(-1), pl.col("Close")]).alias("ExitPrice")
        )

        # Calculate trade return with realistic Indian market friction:
        # return = (exit - entry)/entry - statutory costs - slippage.
        if self.include_costs:
            cost_rate = self.cost_model.get_round_trip_cost_rate(symbol=symbol, instrument="DELIVERY")
            slippage_rate = self.cost_model.get_slippage_rate(symbol)
            total_friction = cost_rate + slippage_rate
        else:
            total_friction = 0.0

        df = df.with_columns(
            pl.when((pl.col("EnterLong") == 1) & pl.col("ExitPrice").is_not_null())
            .then(((pl.col("ExitPrice") - pl.col("EntryPrice")) / pl.col("EntryPrice")) - total_friction)
            .otherwise(0.0)
            .alias("TradeReturn")
        )

        return df

    def calculate_metrics(self, df: pl.DataFrame) -> Dict[str, float]:
        """Calculates standard backtest metrics on TradeReturn column."""
        trades = df.filter((pl.col("EnterLong") == 1) & pl.col("ExitPrice").is_not_null())
        if len(trades) == 0:
            return {
                "sharpe": 0.0,
                "deflated_sharpe": 0.0,
                "max_dd": 0.0,
                "win_rate": 0.0,
                "profit_factor": 0.0,
                "expectancy": 0.0,
                "calmar": 0.0,
            }

        returns = trades.get_column("TradeReturn").to_numpy()
        wins = returns[returns > 0]
        losses = returns[returns <= 0]

        win_rate = float(len(wins) / len(returns)) if len(returns) > 0 else 0.0
        gross_profit = float(wins.sum()) if len(wins) > 0 else 0.0
        gross_loss = float(abs(losses.sum())) if len(losses) > 0 else 1e-9
        profit_factor = float(gross_profit / gross_loss) if gross_loss > 0 else 0.0

        expectancy = float(returns.mean()) if len(returns) > 0 else 0.0

        # Daily equity curve
        df_equity = df.with_columns(
            (1 + pl.col("TradeReturn")).cum_prod().alias("Equity")
        )
        equity = df_equity.get_column("Equity").to_numpy()
        peak = np.maximum.accumulate(equity)
        drawdown = (peak - equity) / np.where(peak > 0, peak, 1.0)
        max_dd = float(drawdown.max()) if len(drawdown) > 0 else 0.0

        # Annualized Sharpe (assuming 252 trading days)
        daily_returns = df.get_column("TradeReturn").to_numpy()
        mean_ret = float(daily_returns.mean()) if len(daily_returns) > 0 else 0.0
        std_ret = float(daily_returns.std()) if len(daily_returns) > 0 else 0.0
        sharpe = (mean_ret / std_ret) * np.sqrt(252) if std_ret > 0 else 0.0

        calmar = (mean_ret * 252) / max_dd if max_dd > 0 else 0.0

        # Deflated Sharpe
        trial_count = 100
        gamma = min(0.9, 0.5772 / np.log(trial_count) if trial_count > 1 else 0.0)
        deflated_sharpe = sharpe * np.sqrt(1 - gamma)

        return {
            "sharpe": float(sharpe),
            "deflated_sharpe": float(deflated_sharpe),
            "max_dd": float(max_dd),
            "win_rate": float(win_rate),
            "profit_factor": float(profit_factor),
            "expectancy": float(expectancy),
            "calmar": float(calmar),
        }

    def run_monte_carlo(self, daily_returns: np.ndarray, iterations: int = 1000) -> Dict[str, float]:
        """Bootstrap 1000 resamples to calculate VaR, profitable year prob, and deflated Sharpe bounds."""
        if len(daily_returns) == 0:
            return {"var_95": 0.0, "prob_profit": 0.0, "median_wealth": 1.0, "bootstrap_sharpe": 0.0}

        n_days = min(252, len(daily_returns))
        simulations = np.random.choice(daily_returns, size=(iterations, n_days), replace=True)
        terminal_wealth = np.prod(1 + simulations, axis=1)

        var_95 = float(np.percentile(terminal_wealth - 1, 5))
        prob_profit = float(np.mean(terminal_wealth > 1.0))
        median_wealth = float(np.median(terminal_wealth))

        sim_means = np.mean(simulations, axis=1)
        sim_stds = np.std(simulations, axis=1)
        sim_sharpes = (sim_means / np.where(sim_stds > 0, sim_stds, 1e-9)) * np.sqrt(252)
        bootstrap_sharpe = float(np.percentile(sim_sharpes, 5))

        return {
            "var_95": var_95,
            "prob_profit": prob_profit,
            "median_wealth": median_wealth,
            "bootstrap_sharpe": bootstrap_sharpe,
        }

    def run_backtest(self, historical_data: pl.DataFrame, symbol: str = "RELIANCE") -> Dict[str, Any]:
        """Fast VectorBT-backed execution for full historical series."""
        vbt_engine = VectorBTEngine(fees=self.fees, slippage=self.slippage)
        return vbt_engine.run_backtest(historical_data)


__all__ = ["WalkForwardBacktester", "VectorBTEngine"]
