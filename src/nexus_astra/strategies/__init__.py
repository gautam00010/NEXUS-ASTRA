"""Practical Quantitative Strategies module for BSE/NSE and Crypto."""

from .orb import generate_orb_signal, backtest_orb_vectorbt
from .vwap_reversion import calculate_vwap_bands, generate_vwap_reversion_signal
from .gap_fade_follow import evaluate_gap_fade_follow
from .momentum_lowvol import select_momentum_lowvol_basket
from .pairs_trading import calculate_pair_spread, generate_pairs_trading_signal
from .crypto_funding import fetch_binance_funding_rate, evaluate_crypto_funding_edge
from .theta_0dte import generate_0dte_strangle_strikes, simulate_0dte_decay

__all__ = [
    "generate_orb_signal",
    "backtest_orb_vectorbt",
    "calculate_vwap_bands",
    "generate_vwap_reversion_signal",
    "evaluate_gap_fade_follow",
    "select_momentum_lowvol_basket",
    "calculate_pair_spread",
    "generate_pairs_trading_signal",
    "fetch_binance_funding_rate",
    "evaluate_crypto_funding_edge",
    "generate_0dte_strangle_strikes",
    "simulate_0dte_decay",
]
