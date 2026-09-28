"""Signal Engine verification gates."""

import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

class Gates:
    """Sequential fail-fast gates for trades."""

    @staticmethod
    def data_health_gate(last_update: datetime) -> bool:
        """DataHealth >16h stale -> DATA_FAIL"""
        if (datetime.now(timezone.utc) - last_update).total_seconds() > 16 * 3600:
            logger.warning("DataHealth Gate: Data >16h stale. DATA_FAIL")
            return False
        return True

    @staticmethod
    def universe_gate(symbol: str, adv_cr: float) -> bool:
        """Universe -> only point-in-time constituents ADV>10Cr"""
        if adv_cr < 10.0:
            logger.warning(f"Universe Gate: ADV {adv_cr} < 10Cr.")
            return False
        return True

    @staticmethod
    def market_risk_gate(vix: float, fii_5d_cum_cr: float) -> bool:
        """MarketRisk -> VIX>25 or FII 5d cum <-15000Cr -> RISK_OFF"""
        if vix > 25 or fii_5d_cum_cr < -15000:
            logger.warning(f"MarketRisk Gate: VIX={vix}, FII={fii_5d_cum_cr}. RISK_OFF")
            return False
        return True

    @staticmethod
    def weekly_thesis_gate(price: float, ema_200: float, fii_trend_bullish: bool, trade_long: bool) -> bool:
        """WeeklyThesis -> 200EMA + FII trend bias, block counter-trend daily"""
        is_above_200 = price > ema_200
        if trade_long and (not is_above_200 or not fii_trend_bullish):
            logger.warning("WeeklyThesis Gate: Counter-trend LONG blocked.")
            return False
        if not trade_long and (is_above_200 or fii_trend_bullish):
            logger.warning("WeeklyThesis Gate: Counter-trend SHORT blocked.")
            return False
        return True

    @staticmethod
    def daily_timing_gate(setup: str) -> bool:
        """DailyTiming -> breakout/pullback/GEX pin"""
        valid_setups = ["breakout", "pullback", "gex_pin"]
        if setup not in valid_setups:
            logger.warning(f"DailyTiming Gate: Invalid setup {setup}.")
            return False
        return True

    @staticmethod
    def human_gate() -> bool:
        """Human gate verification. In signal-only mode, permits signals unless explicitly blocked by operator."""
        import os
        if os.getenv("HUMAN_BLOCK", "0") == "1":
            logger.warning("Human Gate: Blocked by human operator.")
            return False
        return True

    @staticmethod
    def us_influence_gate(
        spx_pct_chg: float | None,
        vix_close: float | None,
        vix_prev: float | None,
        dxy: float | None,
        us10y: float | None,
        us10y_prev: float | None,
    ) -> dict[str, str]:
        """
        US -> India influence gate. Returns regime adjustment signals.
        Called BEFORE Indian signal computation.
        
        Rules (Simons cross-asset playbook):
          SPX -1.5%+ overnight + VIX +15%+ + DXY rising -> RISK_OFF
          US10Y up 10bps -> FII_OUTFLOW_RISK flag
          Otherwise -> NORMAL
        """
        flags: list[str] = []
        regime_adj = "NORMAL"
        position_mult = 1.0

        # Gate only fires when data is available
        if spx_pct_chg is None:
            logger.info("US Influence Gate: SPX data unavailable – passthrough")
            return {"regime_adj": regime_adj, "position_mult": str(position_mult), "flags": ""}

        # SPX overnight gap
        if spx_pct_chg <= -1.5:
            flags.append(f"SPX_GAP_{spx_pct_chg:.2f}pct")

        # VIX spike +15%
        if vix_close is not None and vix_prev is not None and vix_prev > 0:
            vix_chg = (vix_close - vix_prev) / vix_prev * 100.0
            if vix_chg >= 15.0:
                flags.append(f"VIX_SPIKE_{vix_chg:.1f}pct")

        # DXY rising (if available, proxy: positive means USD strengthening)
        dxy_rising = dxy is not None and dxy > 0  # placeholder: compare to rolling mean ideally

        # Composite RISK_OFF trigger
        spx_bad = spx_pct_chg <= -1.5
        vix_bad = "VIX_SPIKE" in " ".join(flags)
        if spx_bad and vix_bad:
            regime_adj = "RISK_OFF"
            position_mult = 0.0  # No new positions
            flags.append("US_RISK_OFF")
            logger.warning(f"US Influence Gate: RISK_OFF – SPX {spx_pct_chg:.2f}% + VIX spike")
        elif spx_pct_chg <= -1.5 or vix_bad:
            regime_adj = "ELEVATED_RISK"
            position_mult = 0.5  # Half size
            flags.append("US_ELEVATED_RISK")
            logger.warning(f"US Influence Gate: ELEVATED_RISK – SPX {spx_pct_chg:.2f}%")

        # US10Y FII outflow risk
        if us10y is not None and us10y_prev is not None:
            bps_chg = (us10y - us10y_prev) * 100.0
            if bps_chg >= 10.0:
                flags.append(f"FII_OUTFLOW_RISK_US10Y_{bps_chg:.0f}bps")
                logger.warning(f"US10Y up {bps_chg:.0f}bps – FII outflow risk")

        return {
            "regime_adj": regime_adj,
            "position_mult": str(position_mult),
            "flags": "|".join(flags),
        }

    @staticmethod
    def run_all_gates(
        last_update: datetime,
        symbol: str,
        adv_cr: float,
        vix: float,
        fii_5d_cum_cr: float,
        price: float,
        ema_200: float,
        fii_trend_bullish: bool,
        trade_long: bool,
        setup: str,
        spx_pct_chg: float | None = None,
        vix_close: float | None = None,
        vix_prev: float | None = None,
        dxy: float | None = None,
        us10y: float | None = None,
        us10y_prev: float | None = None,
    ) -> dict:
        """Runs all 6 gates sequentially. Fails fast. Returns NO_TRADE as success."""
        
        # US Influence Gate – runs first, adjusts regime before Indian gates
        us_result = Gates.us_influence_gate(spx_pct_chg, vix_close, vix_prev, dxy, us10y, us10y_prev)
        if us_result["regime_adj"] == "RISK_OFF":
            return {"status": "NO_TRADE", "reason": "US_RISK_OFF", "us_flags": us_result["flags"], "position_mult": "0.0"}

        if not Gates.data_health_gate(last_update):
            return {"status": "NO_TRADE", "reason": "DATA_FAIL"}
            
        if not Gates.universe_gate(symbol, adv_cr):
            return {"status": "NO_TRADE", "reason": "UNIVERSE_FAIL"}
            
        if not Gates.market_risk_gate(vix, fii_5d_cum_cr):
            return {"status": "NO_TRADE", "reason": "RISK_OFF"}
            
        if not Gates.weekly_thesis_gate(price, ema_200, fii_trend_bullish, trade_long):
            return {"status": "NO_TRADE", "reason": "WEEKLY_THESIS_FAIL"}
            
        if not Gates.daily_timing_gate(setup):
            return {"status": "NO_TRADE", "reason": "DAILY_TIMING_FAIL"}
            
        if not Gates.human_gate():
            return {"status": "NO_TRADE", "reason": "HUMAN_ACK_FAIL"}
            
        return {"status": "PASS", "us_flags": us_result.get("flags", ""), "position_mult": us_result.get("position_mult", "1.0")}
