"""Model 5: Crypto-Equity Cross-Asset Regime Model (Crypto Leads NSE by 48 Hours).

Macro Mechanism:
- Global Liquidity Transmission & 24/7 Price Discovery:
  * Crypto markets trade 24/7 and serve as the hyper-sensitive canary in the coal mine for global dollar liquidity.
  * BTC Dominance (BTC.D) and Stablecoin Capitalization (USDT + USDC supply) lead emerging market equities.
- Regime 1: High-Beta Risk-On (Bullish Indian Midcaps for ~2 Weeks):
  * Trigger: BTC Dominance declines (< 54%) WHILE Stablecoin Market Cap is rising (+2% over 14 days).
  * Meaning: Liquidity is overflowing from Bitcoin into long-tail crypto assets and global risk assets.
  * Transmission: Indian Midcap / Smallcap momentum outperforms NIFTY 50 over the subsequent 2 weeks.
- Regime 2: Severe Flight to Safety / Risk-Off (Defensive Rotation to FMCG / Pharma):
  * Trigger: BTC Dominance surges sharply (> 58%) OR Stablecoin Market Cap contracts.
  * Meaning: Crypto liquidity draining into cash; institutional margin calls looming.
  * Transmission: NSE high-beta growth stocks sell off within 48 hours. Shift to defensive FMCG/Pharma.
"""

from __future__ import annotations
import logging
from typing import Any, Dict

logger = logging.getLogger(__name__)


def evaluate_crypto_equity_lead_lag(
    btc_dominance_pct: float = 52.8,        # e.g. 52.8% (falling below 54%)
    btc_dominance_14d_change: float = -1.8, # BTC.D dropped 1.8%
    stablecoin_mcap_14d_pct: float = 3.2,   # +3.2% net stablecoin issuance (expansion)
    btc_price: float = 86972.0,
) -> Dict[str, Any]:
    """
    Evaluates crypto macro indicators to determine the risk-on/risk-off regime for Indian equities.
    """
    is_risk_on_expansion = (
        btc_dominance_14d_change < -0.5 and
        stablecoin_mcap_14d_pct > 1.0 and
        btc_dominance_pct < 55.0
    )

    is_risk_off_contraction = (
        btc_dominance_14d_change > 2.0 or
        stablecoin_mcap_14d_pct < -1.0 or
        btc_dominance_pct >= 58.0
    )

    if is_risk_on_expansion:
        regime = "CRYPTO_EXPANSION_RISK_ON"
        indian_equity_strategy = "OVERWEIGHT_INDIAN_MIDCAPS_GROWTH"
        favored_nse_sectors = ["NIFTY MIDCAP 100", "NIFTY AUTO", "NIFTY REALTY"]
        defensive_allocation_pct = 10.0
        guidance = (
            f"BTC dominance falling ({btc_dominance_14d_change:+.1f}%) with expanding stablecoin supply ({stablecoin_mcap_14d_pct:+.1f}%). "
            "Global liquidity is aggressive. Crypto leads Dalal Street by 48h; overweight high-beta Indian midcaps for ~2 weeks."
        )
    elif is_risk_off_contraction:
        regime = "CRYPTO_CONTRACTION_RISK_OFF"
        indian_equity_strategy = "DEFENSIVE_ROTATION_FMCG_PHARMA"
        favored_nse_sectors = ["NIFTY FMCG", "NIFTY PHARMA", "NIFTY IT"]
        defensive_allocation_pct = 60.0
        guidance = (
            f"BTC dominance surging ({btc_dominance_pct:.1f}%) or stablecoin supply draining. "
            "Flight to dollar cash. Emerging market equities face 48h liquidity drag; rotate immediately into FMCG and Pharma."
        )
    else:
        regime = "NEUTRAL_CRYPTO_TRANSMISSION"
        indian_equity_strategy = "BALANCED_CORE_NIFTY_50"
        favored_nse_sectors = ["NIFTY 50", "NIFTY BANK"]
        defensive_allocation_pct = 30.0
        guidance = "Crypto macro liquidity metrics are stable. Maintain benchmark index allocation."

    return {
        "model": "Model 5: Crypto-Equity Regime (48h Lead-Lag)",
        "btc_dominance_pct": round(btc_dominance_pct, 1),
        "btc_dominance_14d_change": round(btc_dominance_14d_change, 2),
        "stablecoin_14d_change_pct": round(stablecoin_mcap_14d_pct, 2),
        "regime": regime,
        "regime_classification": "HIGH_BETA_RISK_ON" if regime == "CRYPTO_EXPANSION_RISK_ON" else ("DEFENSIVE_RISK_OFF" if regime == "CRYPTO_CONTRACTION_RISK_OFF" else "NEUTRAL"),
        "indian_equity_strategy": indian_equity_strategy,
        "nse_positioning_stance": indian_equity_strategy,
        "favored_nse_sectors": favored_nse_sectors,
        "defensive_allocation_pct": defensive_allocation_pct,
        "lead_lag_window": "48 Hours Crypto Lead -> 2-Week Equity Transmission",
        "guidance": guidance,
    }
