"""NEXUS-ASTRA Composite Signal Orchestration Engine."""

from __future__ import annotations

import logging
import math
from datetime import datetime, timezone, date, time as dt_time
from typing import Any

import polars as pl
from nexus_astra.signal_engine.gates import Gates
from nexus_astra.data_ingestion.database import DatabaseManager, database_manager
from nexus_astra.feature_engineering.fair_value_engine import FairValueEngine
from nexus_astra.data_ingestion.super_investor_fetcher import SuperInvestorFetcher
import asyncio

logger = logging.getLogger(__name__)

HISTORICAL_WIN_RATES = {
    "CALM_BULL": 0.64,
    "VOLATILE_BULL": 0.58,
    "CALM_BEAR": 0.52,
    "BEAR_MOMENTUM": 0.60,
    "STRESS_DRAIN": 0.62,
    "EXPANSION_CARRY": 0.65,
    "NEUTRAL_CALM": 0.50,
}

class SignalOrchestrator:
    """The central decision engine integrating options, crypto, alternative, macro, and price layers."""

    def __init__(self, db_manager: DatabaseManager | None = None) -> None:
        self.db_manager = db_manager or database_manager
        self.fv_engine = FairValueEngine()
        self.si_fetcher = SuperInvestorFetcher()

    def compute_composite_signal(
        self,
        symbol: str,
        regime_state: str,
        options_data: dict[str, Any],
        crypto_data: dict[str, Any],
        alternative_data: dict[str, Any],
        macro_data: dict[str, Any],
        price_history: pl.DataFrame,
        us_data: dict[str, float | None] | None = None,
    ) -> dict[str, Any] | None:
        if price_history.is_empty():
            logger.warning(f"No price history available for {symbol}")
            return None
            
        latest = price_history.row(-1, named=True)
        
        # 0a. US Influence: cross-asset regime adjustment FIRST (Simons cross-asset dep.)
        us_data = us_data or {}
        spx_pct_chg: float | None = us_data.get("spx_pct_chg")
        vix_close: float | None = us_data.get("vix_close")
        dxy: float | None = us_data.get("dxy")
        us10y: float | None = us_data.get("us10y")
        
        # Cross-asset NIFTY direction prior: if SPX strongly positive, lean bullish
        us_bias = 0.0
        if spx_pct_chg is not None:
            if spx_pct_chg >= 1.0:
                us_bias = 15.0   # +15 pts bullish nudge
                logger.info(f"US Influence: SPX +{spx_pct_chg:.2f}% -> bullish prior on NIFTY")
            elif spx_pct_chg <= -1.0:
                us_bias = -15.0  # -15 pts bearish nudge
                logger.info(f"US Influence: SPX {spx_pct_chg:.2f}% -> bearish prior on NIFTY")

        # US10Y FII outflow risk flag injection into macro_data
        if us10y is not None:
            macro_data.setdefault("us10y", us10y)
            
        # 0. Compute real gate verification parameters from data
        last_dt = latest.get("date")
        if isinstance(last_dt, datetime):
            last_update = last_dt if last_dt.tzinfo else last_dt.replace(tzinfo=timezone.utc)
        elif isinstance(last_dt, date):
            last_update = datetime.combine(last_dt, dt_time(10, 0), tzinfo=timezone.utc)
        else:
            last_update = datetime.now(timezone.utc)

        price_val = float(latest.get("close", 0.0) or 0.0)
        vol_val = float(latest.get("volume", 0) or 0)
        if symbol.startswith("^"):
            adv_cr = 1000.0  # Index liquidity represents institutional market depth
        else:
            adv_cr = (price_val * vol_val) / 1e7 if price_val > 0 and vol_val > 0 else 0.0

        ema_200 = float(latest.get("ema_200", 0.0) or 0.0)
        fii_flow = float(alternative_data.get("fii_net_flow", 0.0) or 0.0)
        fii_bullish = fii_flow > 0

        # Weekly thesis direction
        if price_val >= ema_200 and fii_bullish:
            trade_long = True
        elif price_val < ema_200 and not fii_bullish:
            trade_long = False
        else:
            trade_long = (price_val >= ema_200)

        # Daily timing setup: breakout or pullback
        high_20 = price_history["high"].tail(20).max() if "high" in price_history.columns and not price_history.is_empty() else price_val
        if high_20 and price_val >= float(high_20) * 0.99:
            setup = "breakout"
        elif ema_200 > 0 and abs(price_val - ema_200) / ema_200 < 0.03:
            setup = "pullback"
        else:
            setup = "gex_pin"

        gate_res = Gates.run_all_gates(
            last_update=last_update,
            symbol=symbol,
            adv_cr=adv_cr,
            vix=float(macro_data.get("us_vix", 15.0) or 15.0),
            fii_5d_cum_cr=fii_flow,
            price=price_val,
            ema_200=ema_200,
            fii_trend_bullish=fii_bullish,
            trade_long=trade_long,
            setup=setup,
            spx_pct_chg=spx_pct_chg,
            vix_close=vix_close,
            dxy=dxy,
            us10y=us10y,
        )
        if gate_res["status"] == "NO_TRADE":
            logger.warning(f"Gates failed: {gate_res['reason']}")
            return None
        """Combine all input streams, apply directional filters, and compute composite trade signal details."""
        logger.info(f"Orchestrating composite signal for {symbol} under regime {regime_state}...")

        # 1. Compute Macro Layer (30% weight)
        # US Lead-Lag (15%)
        macro_flags = macro_data.get("flags", "") or ""
        us_lead_lag_score = 0.0
        us_lead_lag_conf = 0.5
        if "US_MOMENTUM_CARRY" in macro_flags:
            us_lead_lag_score = 100.0
            us_lead_lag_conf = 0.9
        elif macro_data.get("us_vix", 0.0) > 28.0:
            us_lead_lag_score = -80.0
            us_lead_lag_conf = 0.8
        else:
            us_lead_lag_conf = 0.6

        # FII/DII Flow (15%)
        fii_dii_score = 0.0
        fii_dii_conf = 0.6
        fii_net = alternative_data.get("fii_net_flow", 0.0) # From FII/DII flows
        if fii_net > 0:
            fii_dii_score = min(100.0, (fii_net / 3000.0) * 100.0)
            fii_dii_conf = 0.8
        elif fii_net < 0:
            fii_dii_score = max(-100.0, (fii_net / 3000.0) * 100.0)
            fii_dii_conf = 0.8

        # 2. Compute Microstructure Layer (25% weight)
        # PCR (15%)
        pcr = options_data.get("pcr", 1.0)
        pcr_score = 0.0
        pcr_conf = 0.6
        if pcr >= 1.25:
            pcr_score = 100.0
            pcr_conf = 0.85
        elif pcr <= 0.65:
            pcr_score = -100.0
            pcr_conf = 0.85
        else:
            pcr_score = ((pcr - 0.95) / 0.3) * 100.0
            pcr_score = max(-100.0, min(100.0, pcr_score))

        # Max Pain (5%)
        max_pain = options_data.get("max_pain", 0.0)
        spot_price = options_data.get("spot_price", 0.0)
        max_pain_score = 0.0
        max_pain_conf = 0.5
        if spot_price > 0.0 and max_pain > 0.0:
            diff_pct = (max_pain - spot_price) / spot_price * 100.0
            if diff_pct > 1.5:
                max_pain_score = 100.0
                max_pain_conf = 0.75
            elif diff_pct < -1.5:
                max_pain_score = -100.0
                max_pain_conf = 0.75

        # OFFSHORE NOISE CAP (Crypto / Whale / Funding) - max 2% weight
        offshore_score = crypto_data.get("crypto_smart_money_score", 50.0) - 50.0
        offshore_conf = 0.5
        
        # 3. Advanced Quant Math Layer (28% weight replaces alt data crypto)
        # VAR Forecast (10%)
        var_val = latest.get("var_2_lag_forecast", 0.0) if 'latest' in locals() else 0.0
        var_score = max(-100.0, min(100.0, var_val * 10000.0))
        var_conf = 0.8
        
        # Black-Litterman / HRP (13%)
        bl_val = latest.get("bl_implied_view", 0.0) if 'latest' in locals() else 0.0
        bl_score = max(-100.0, min(100.0, bl_val * 500.0))
        bl_conf = 0.8
        
        # Sentiment (5%): News
        news_sent = alternative_data.get("news_sentiment_score", 0.0)
        sentiment_score = news_sent * 100.0
        sentiment_score = max(-100.0, min(100.0, sentiment_score))
        sentiment_conf = 0.75

        # 4. Compute Cross-Market Layer (20% weight)
        # ADRs / Macro correlations (VIX, DXY, USD-INR) + US overnight cross-asset
        cross_market_score = 0.0
        cross_market_conf = 0.6
        macro_score = macro_data.get("macro_regime_score", 0.0)
        cross_market_score = macro_score + us_bias  # US close as NIFTY open prior
        cross_market_score = max(-100.0, min(100.0, cross_market_score))
        cross_market_conf = 0.8 if (macro_flags or spx_pct_chg is not None) else 0.6

        # Weighted composite score sum
        weighted_score = (
            (us_lead_lag_score * 0.15 + fii_dii_score * 0.15) +
            (pcr_score * 0.15 + max_pain_score * 0.05 + offshore_score * 0.02) +
            (var_score * 0.10 + bl_score * 0.13 + sentiment_score * 0.05) +
            (cross_market_score * 0.20)
        )

        direction = "LONG" if weighted_score >= 0 else "SHORT"
        composite_score = abs(weighted_score)
        
        # Apply US gate position multiplier (0.5 = elevated_risk, 0.0 = risk_off)
        us_position_mult = float(gate_res.get("position_mult", "1.0"))

        # Weighted composite confidence
        composite_confidence = (
            (us_lead_lag_conf * 0.15 + fii_dii_conf * 0.15) +
            (pcr_conf * 0.15 + max_pain_conf * 0.05 + offshore_conf * 0.02) +
            (var_conf * 0.10 + bl_conf * 0.13 + sentiment_conf * 0.05) +
            (cross_market_conf * 0.20)
        )

        # Compute independent layer scores for agreement check
        layer_macro = (us_lead_lag_score * 0.15 + fii_dii_score * 0.15) / 0.30
        layer_micro = (pcr_score * 0.15 + max_pain_score * 0.05) / 0.20
        layer_alt = (var_score * 0.10 + bl_score * 0.13 + sentiment_score * 0.05) / 0.28
        layer_cross = cross_market_score

        # Check agreement direction
        layers = [layer_macro, layer_micro, layer_alt, layer_cross]
        agreement_count = sum(1 for score in layers if (direction == "LONG" and score >= 0) or (direction == "SHORT" and score < 0))

        # Strict Filter Rule: Score > 75 AND at least 3 layers agree on direction
        if composite_score <= 75.0 or agreement_count < 3:
            logger.info(f"Signal rejected. Composite: {composite_score:.2f} <= 75 or Layer Agreement: {agreement_count} < 3.")
            return None

        # Compute Fair Value and Health Score
        fv_metrics = self.fv_engine.compute_fair_value_and_health(price_history.tail(1), price_val)
        
        # Compute Super Investor Accumulation
        si_metrics = self.si_fetcher.fetch_accumulation(symbol)
        si_weight = si_metrics.get("quality_conviction_weight", 0.0) * 100.0 # Max 10.0
        
        # Determine Dominant Driver Factor
        pcr_funding_contr = abs(pcr_score * 0.15) + abs(offshore_score * 0.02) + abs(var_score * 0.10)
        fii_smart_contr = abs(fii_dii_score * 0.15) + abs(bl_score * 0.13) + abs(si_weight)
        macro_contr = abs(us_lead_lag_score * 0.15) + abs(cross_market_score * 0.20)

        if macro_contr >= fii_smart_contr and macro_contr >= pcr_funding_contr:
            dominant_factor = "MACRO"
        elif fii_smart_contr >= pcr_funding_contr:
            dominant_factor = "FII_SMART_MONEY"
        else:
            dominant_factor = "MICRO"

        # Johansen VECM spread duration: Duration = ln(0.5) / ln(1 - 1/theta)
        from nexus_astra.signal_engine.duration_engine import JohansenVECMDurationEngine
        duration_metrics = JohansenVECMDurationEngine.compute_duration(
            symbol=symbol,
            price_history=price_history,
            dominant_factor=dominant_factor,
        )
        duration = duration_metrics.duration_category

        # Look up win rate and compute expected return using fractional Kelly
        win_rate = HISTORICAL_WIN_RATES.get(regime_state, 0.55)
        avg_win_pct = 2.0
        avg_loss_pct = 1.0
        expected_return_pct = (win_rate * avg_win_pct) - ((1.0 - win_rate) * avg_loss_pct)

        # 20% fractional Kelly: f* = [W*(R+1)-1]/R * 0.20
        R = avg_win_pct / avg_loss_pct
        kelly_raw = (win_rate * (R + 1.0) - 1.0) / R
        kelly_20pct = max(0.0, kelly_raw * 0.20) * 100.0
        # Hard caps: max 15% single position
        position_size_pct = min(kelly_20pct, 15.0)
        # Apply US influence gate multiplier (1.0=normal | 0.5=elevated_risk | 0.0=risk_off)
        position_size_pct = position_size_pct * us_position_mult
        position_size_pct = max(0.0, min(15.0, position_size_pct))

        stop_loss_pct = 1.5 if direction == "LONG" else 1.0

        # Devil's advocate rationale: counter-case FIRST (behavioral spec)
        us_flag_str = gate_res.get("us_flags", "")
        rationale = [
            f"[COUNTER-CASE] US flags: {us_flag_str or 'none'}. SPX overnight: {f'{spx_pct_chg:+.2f}%' if spx_pct_chg is not None else 'unavailable'}.",
            f"Macro Regime {regime_state} win rate {win_rate:.0%}. Composite {composite_score:.1f} | {agreement_count}/4 layers agree.",
            f"PCR {pcr:.2f} -> {'bullish' if pcr_score >= 0 else 'bearish'} microstructure. US bias applied: {us_bias:+.1f}pts.",
            f"Duration {duration_metrics.duration_display} | Rule: {duration_metrics.regime_rule}.",
            f"Position sized at {position_size_pct:.1f}% (Kelly_20%={kelly_20pct:.1f}%, US_mult={us_position_mult:.1f}x, cap=15%).",
        ]

        invalidation_conditions = [
            "SPX gap < -1.5% overnight OR VIX spike +15% -> reduce/exit.",
            "US10Y rises > 10bps -> FII outflow unwind risk.",
            "VIX > 25 OR FII 5d cumulative < -15,000 Cr.",
            "Composite score < 50 OR < 3 of 4 layers agree.",
        ]

        return {
            "symbol": symbol,
            "direction": direction,
            "confidence": float(composite_confidence),
            "duration": duration,
            "duration_days": duration_metrics.duration_days,
            "duration_display": duration_metrics.duration_display,
            "duration_theta": duration_metrics.theta,
            "duration_z_score": duration_metrics.z_score,
            "duration_garch_vol_pct": duration_metrics.garch_vol_pct,
            "duration_garch_vol_state": duration_metrics.garch_vol_state,
            "duration_regime_rule": duration_metrics.regime_rule,
            "duration_formula": duration_metrics.formula,
            "expected_return_pct": float(expected_return_pct),
            "stop_loss_pct": stop_loss_pct,
            "position_size_pct": float(position_size_pct),
            "kelly_raw_pct": round(kelly_raw * 100, 3),
            "us_position_mult": us_position_mult,
            "us_spx_pct_chg": spx_pct_chg,
            "us_flags": us_flag_str,
            "rationale": rationale,
            "invalidation_conditions": invalidation_conditions,
            "composite_score": float(composite_score),
            "layer_agreement_count": agreement_count,
            "fair_value": float(fv_metrics["intrinsic_value"]),
            "fair_value_upside_pct": float(fv_metrics["fair_value_upside_pct"]),
            "health_score": float(fv_metrics["health_score"]),
            "super_investor_accumulation": float(si_metrics["super_investor_accumulation"]),
            "fii_accumulation_flag": bool(si_metrics["fii_accumulation_flag"])
        }
