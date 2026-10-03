"""VectorBT Engine for hyper-fast C++/Numba backtesting."""
import vectorbt as vbt
import polars as pl
import pandas as pd

class VectorBTEngine:
    def __init__(self, fees: float = 0.001, slippage: float = 0.001):
        self.fees = fees
        self.slippage = slippage
        
    def run_backtest(self, price_data: pl.DataFrame):
        """
        Runs a vectorized backtest using vectorbt Portfolio.from_signals.
        Expects a Polars DataFrame with Date and Close columns.
        """
        df_pd = price_data.to_pandas()
        if "Date" in df_pd.columns:
            df_pd.set_index("Date", inplace=True)
            
        close = df_pd["Close"]
        
        # Fast MA crossover generation using Numba-compiled vectorbt indicator
        fast_ma = vbt.MA.run(close, 10)
        slow_ma = vbt.MA.run(close, 50)
        
        entries = fast_ma.ma_crossed_above(slow_ma.ma)
        exits = fast_ma.ma_crossed_below(slow_ma.ma)
        
        portfolio = vbt.Portfolio.from_signals(
            close,
            entries,
            exits,
            fees=self.fees,
            slippage=self.slippage,
            freq='1D'
        )
        
        return {
            "sharpe": float(portfolio.sharpe_ratio()),
            "max_drawdown": float(portfolio.max_drawdown()),
            "win_rate": float(portfolio.trades.win_rate()),
            "profit_factor": float(portfolio.trades.profit_factor()),
            "total_return": float(portfolio.total_return())
        }
