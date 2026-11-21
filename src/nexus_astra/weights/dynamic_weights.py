"""Regime-adaptive, performance-aware dataset weights."""

from __future__ import annotations

import math
import re
from collections.abc import Iterable, Mapping
from typing import Any


BASE_WEIGHTS: dict[str, float] = {
    "momentum": 0.20,
    "mean_reversion": 0.20,
    "macro_fred": 0.15,
    "fii_dii": 0.10,
    "sentiment_news": 0.10,
    "fundamentals_edgar": 0.15,
    "technical_orb_vwap_gap": 0.10,
}

REGIME_MULTIPLIERS: dict[str, dict[str, float]] = {
    "TRENDING": {
        "momentum": 2.0, "technical_orb_vwap_gap": 1.5,
        "mean_reversion": 0.5, "sentiment_news": 1.2,
    },
    "MEAN_REVERTING": {
        "mean_reversion": 2.0, "technical_orb_vwap_gap": 1.2,
        "momentum": 0.5, "garch": 1.5,
    },
    "HIGH_VOL_SHOCK": {
        "garch": 2.0, "mean_reversion": 1.5, "momentum": 0.3,
        "macro_fred": 0.8,
    },
    "MACRO_RISK_OFF": {
        "macro_fred": 2.0, "fii_dii": 2.0,
        "fundamentals_edgar": 1.5, "momentum": 0.5,
    },
}


def _normalize(weights: Mapping[str, float]) -> dict[str, float]:
    positive = {str(k): max(0.0, float(v)) for k, v in weights.items()}
    total = sum(positive.values())
    if total <= 0:
        count = max(1, len(positive))
        return {k: 1.0 / count for k in positive}
    return {k: v / total for k, v in positive.items()}


def recency_sharpe(trades: Iterable[Mapping[str, Any]], decay: float = 0.94) -> float:
    """Exponentially weighted Sharpe proxy; most recent trade has weight one."""
    rows = list(trades)
    if not rows:
        return 1.0
    pnls = [float(r.get("pnl", r.get("pnl_pct", r.get("return", 0.0)))) for r in rows]
    weighted = []
    weights = []
    for age, pnl in enumerate(reversed(pnls)):
        w = decay ** age
        weighted.append(pnl * w)
        weights.append(w)
    mean = sum(weighted) / max(sum(weights), 1e-12)
    variance = sum((pnl - mean) ** 2 * decay ** i for i, pnl in enumerate(reversed(pnls)))
    vol = math.sqrt(max(variance / max(sum(decay ** i for i in range(len(pnls))), 1e-12), 1e-12))
    return mean / vol


def detect_regime(
    *,
    vix: float = 15.0,
    adx: float = 20.0,
    garch_vol: float = 0.15,
    pcr: float = 1.0,
    macro_risk_score: float = 0.0,
    hmm_regime: str | None = None,
) -> str:
    """Map HMM/ADX/GARCH/VIX/PCR inputs to one of the four weighting regimes."""
    if macro_risk_score >= 0.65 or (hmm_regime or "").upper() in {"MACRO_RISK_OFF", "BEAR_MOMENTUM", "STRESS_DRAIN"}:
        return "MACRO_RISK_OFF"
    if vix >= 25.0 or garch_vol >= 0.30:
        return "HIGH_VOL_SHOCK"
    if adx >= 25.0 or (hmm_regime or "").upper() in {"TRENDING", "TRENDING_LOW_VOL", "CALM_BULL", "EXPANSION_CARRY"}:
        return "TRENDING"
    if (hmm_regime or "").upper() in {"MEAN_REVERTING", "MEAN_REVERTING_SIDEWAYS", "NEUTRAL_CALM"}:
        return "MEAN_REVERTING"
    return "MEAN_REVERTING" if adx < 20.0 or pcr >= 1.15 else "TRENDING"


class DynamicWeightEngine:
    def calculate_weights(
        self,
        regime: str,
        performance: Mapping[str, Mapping[str, float]] | None = None,
        realized_vol: Mapping[str, float] | None = None,
        thesis: str = "",
        context: Mapping[str, Any] | None = None,
    ) -> dict[str, float]:
        regime = str(regime).upper().replace(" ", "_")
        aliases = {
            "TRENDING_LOW_VOL": "TRENDING",
            "MEAN_REVERTING_SIDEWAYS": "MEAN_REVERTING",
            "HIGH_VOL_PANIC": "HIGH_VOL_SHOCK",
            "CALM_BULL": "TRENDING",
            "VOLATILE_BULL": "TRENDING",
            "CALM_BEAR": "MACRO_RISK_OFF",
            "BEAR_MOMENTUM": "MACRO_RISK_OFF",
            "STRESS_DRAIN": "HIGH_VOL_SHOCK",
            "EXPANSION_CARRY": "TRENDING",
            "NEUTRAL_CALM": "MEAN_REVERTING",
        }
        regime = aliases.get(regime, regime)
        if regime not in REGIME_MULTIPLIERS:
            regime = "MEAN_REVERTING"

        performance = performance or {}
        realized_vol = realized_vol or {}
        context = context or {}
        weights = {}
        for name, base in BASE_WEIGHTS.items():
            multiplier = float(REGIME_MULTIPLIERS[regime].get(name, 1.0))
            stats = performance.get(name, {})
            sharpe = float(stats.get("sharpe", stats.get("recent_sharpe", 1.0)))
            adaptive = max(0.2, sharpe)
            vol = float(realized_vol.get(name, 0.15) or 0.15)
            vol_factor = 1.0 / max(vol, 0.05)
            weights[name] = base * multiplier * adaptive * vol_factor

        # GARCH is an explicitly contextual risk dataset even though it shares the
        # volatility risk sleeve with technical data.
        if "garch" not in weights:
            weights["garch"] = weights["technical_orb_vwap_gap"] * float(REGIME_MULTIPLIERS[regime].get("garch", 1.0))
        if "pair_cointegration" not in weights:
            weights["pair_cointegration"] = weights["mean_reversion"] * 0.75

        text = f"{thesis} {context.get('thesis', '')}".lower()
        boosts = {
            "fii_dii": (r"\bfii\b|accumulation|institutional flow", 1.35),
            "mean_reversion": (r"z[- ]?score|mean[- ]reversion|pair", 1.30),
            "garch": (r"garch|high vol|low vol|volatility shock", 1.40),
            "macro_fred": (r"macro|pcr|carry", 1.35),
            "pair_cointegration": (r"cointegration|stat[- ]arb|pairs?|bank nifty", 1.50),
            "fundamentals_edgar": (r"edgar|20[- ]f|fundamental|filing", 1.40),
            "momentum": (r"momentum|trend|200-?ema|lead[- ]lag", 1.25),
        }
        for name, (pattern, factor) in boosts.items():
            if re.search(pattern, text):
                weights[name] = weights.get(name, 0.01) * factor

        weights = _normalize(weights)
        # Negative-Sharpe datasets cannot disappear; they retain a 5% recovery floor.
        for name, stats in performance.items():
            sharpe = float(stats.get("sharpe", stats.get("recent_sharpe", 1.0)))
            if sharpe < 0 and name in weights:
                weights[name] = max(0.05, weights[name])
        weights = _normalize(weights)
        return weights

    get_dynamic_weights = calculate_weights
    rebalance_weights_daily = calculate_weights


def calculate_dynamic_weights(regime: str = "MEAN_REVERTING", **kwargs: Any) -> dict[str, float]:
    return DynamicWeightEngine().calculate_weights(regime=regime, **kwargs)

