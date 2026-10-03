"""NEXUS-ASTRA end-to-end daily pipeline entry point."""

from __future__ import annotations

import asyncio
import json
import sys
import time
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import polars as pl

import logging
import logging.handlers

PROJECT_ROOT = Path(__file__).resolve().parent
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))


def _configure_logging() -> None:
    """Configure daily rotating log to logs/astra_YYYY-MM-DD.log."""
    logs_dir = PROJECT_ROOT / "logs"
    logs_dir.mkdir(exist_ok=True)
    log_file = logs_dir / f"astra_{datetime.now().strftime('%Y-%m-%d')}.log"
    fmt = logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(name)-35s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    fh = logging.FileHandler(log_file, encoding="utf-8")
    fh.setFormatter(fmt)
    fh.setLevel(logging.DEBUG)
    sh = logging.StreamHandler()
    sh.setFormatter(fmt)
    sh.setLevel(logging.INFO)
    root = logging.getLogger()
    root.setLevel(logging.DEBUG)
    # Idempotent: add file handler only if not already added
    if not any(isinstance(h, logging.FileHandler) for h in root.handlers):
        root.addHandler(fh)
    if not any(isinstance(h, logging.StreamHandler) and not isinstance(h, logging.FileHandler) for h in root.handlers):
        root.addHandler(sh)


_configure_logging()


from nexus_astra.data_ingestion import (
    DailyPriceData,
    InstitutionalFlows,
    MacroRegime,
    PricesRaw,
    MarketDataFetcher,
    NSEOptionsFetcher,
    database_manager,
)
from nexus_astra.data_ingestion.event_calendar import EventRisk
from nexus_astra.delivery.telegram_delivery import send_telegram_signal
from nexus_astra.feature_engineering import AlphaFeatures, detect_market_regime, GammaExposure, WhaleIntelligence
from nexus_astra.feature_engineering.sector_rotation import SectorRotation
from nexus_astra.feature_engineering.dark_pool_proxy import DarkPoolIndia
from nexus_astra.feature_engineering.macro_overlay import MacroRegime as MacroOverlayEngine
from nexus_astra.ml_models import EnsembleEngine
from nexus_astra.risk_management import calculate_final_capital_allocation_pct
from nexus_astra.signal_engine.composite_orchestrator import SignalOrchestrator
from nexus_astra.monitoring.circuit_breaker import CircuitBreaker
from nexus_astra.monitoring.health_monitor import SystemHealth
from nexus_astra.backtesting.paper_trader import PaperTrader

logger = logging.getLogger(__name__)

async def pipeline_run(circuit_breaker: CircuitBreaker, health_monitor: SystemHealth, paper_trader: PaperTrader) -> dict[str, Any]:
    """Core logic of the NEXUS-ASTRA pipeline."""
    
    start_time = time.time()
    
    # 1. Load Data Layer from SQLite
    daily_prices = _load_table_as_polars(PricesRaw)
    if daily_prices.is_empty():
        daily_prices = _load_table_as_polars(DailyPriceData)
    daily_prices = _standardize_date_column(daily_prices, "trade_date")
    daily_prices = _standardize_date_column(daily_prices, "Date")
        
    institutional_flows = _load_table_as_polars(InstitutionalFlows)
    institutional_flows = _standardize_date_column(institutional_flows, "flow_date")
    institutional_flows = _standardize_date_column(institutional_flows, "Date")

    macro_regime = _load_table_as_polars(MacroRegime)
    macro_regime = _standardize_date_column(macro_regime, "regime_date")
    macro_regime = _standardize_date_column(macro_regime, "Date")

    # Validate essential data: if prices or flows are missing -> return DATA_FAIL
    if daily_prices.is_empty() or institutional_flows.is_empty():
        no_data_output = {
            "status": "DATA_FAIL",
            "reason": "Essential market data missing (PricesRaw / InstitutionalFlows empty)",
            "confidence": 0.0,
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "signals_sent": 0,
        }
        print("CRITICAL: Market data missing. Returning DATA_FAIL.")
        return no_data_output

    # Calculate spot price and options metrics safely
    nifty_prices = daily_prices.filter(pl.col("symbol") == "^NSEI").sort("date")
    spot_price = float(nifty_prices["close"][-1]) if not nifty_prices.is_empty() and "close" in nifty_prices.columns else 22000.0

    pcr = 1.0
    max_pain = spot_price
    zero_gamma = spot_price
    pin_risk = 0.0
    options_data = {
        "spot_price": spot_price,
        "pcr": pcr,
        "max_pain": max_pain,
        "zero_gamma": zero_gamma,
        "pin_risk": pin_risk,
    }

    # Macro and Sentiment
    news_sentiment_score = 0.0
    regime_state = "CALM_BULL"
    if not macro_regime.is_empty() and "regime_label" in macro_regime.columns:
        last_regime = macro_regime.sort("date")["regime_label"][-1]
        if last_regime:
            regime_state = str(last_regime)

    crypto_data = {
        "crypto_smart_money_score": 50.0,
        "flags": ""
    }

    # 2. Construct Alternative Data dict
    fii_net = 0.0
    if not institutional_flows.is_empty():
        fii_net = float(institutional_flows["net_fii"][-1]) if "net_fii" in institutional_flows.columns else 0.0

    alternative_data = {
        "fii_net_flow": fii_net,
        "news_sentiment_score": news_sentiment_score,
    }

    # 3. Construct Macro Data dict
    us_vix = 15.0
    macro_score = 0.0
    macro_flags = ""
    if not macro_regime.is_empty():
        latest_macro = macro_regime.sort("date").tail(1).to_dicts()[0]
        us_vix = float(latest_macro.get("us_vix", 15.0) or 15.0)
        macro_score = float(latest_macro.get("macro_regime_score", 0.0) or 0.0)
        macro_flags = latest_macro.get("flags", "") or ""

    macro_data = {
        "us_vix": us_vix,
        "macro_regime_score": macro_score,
        "flags": macro_flags
    }
    
    # 3.5 Fetch additional data sources in parallel (fail-safe: each returns None on error)
    from nexus_astra.data_ingestion.trends_fetcher import TrendsFetcher
    from nexus_astra.data_ingestion.edgar_fetcher import EdgarFetcher
    from nexus_astra.data_ingestion.finnhub_fetcher import FinnhubFetcher, USMarketFetcher
    from nexus_astra.data_ingestion.crypto_fetcher import CryptoFetcher
    from nexus_astra.data_ingestion.zerodha_fetcher import ZerodhaFetcher
    from nexus_astra.feature_engineering.sentiment_engine import NewsSentiment

    trends_fetcher = TrendsFetcher()
    edgar_fetcher = EdgarFetcher()
    finnhub_fetcher = FinnhubFetcher()
    crypto_fetcher = CryptoFetcher()
    us_fetcher = USMarketFetcher()
    _zerodha = ZerodhaFetcher()  # Logs skip if no key

    trends_z, edgar_filings, finnhub_news, crypto_prices, us_data = await asyncio.gather(
        trends_fetcher.get_trends_score(),
        edgar_fetcher.fetch_filings("INFY"),
        finnhub_fetcher.get_news(),
        crypto_fetcher.fetch_prices(),
        us_fetcher.fetch_us_snapshot(),
    )

    crypto_data["prices"] = crypto_prices if crypto_prices else None

    # Override us_vix from live Finnhub if available (beats DB staleness)
    if us_data.get("vix_close") is not None:
        macro_data["us_vix"] = us_data["vix_close"]

    # Process sentiment with all available sources
    sentiment_engine = NewsSentiment()
    sentiment_result = await sentiment_engine.run_pipeline(
        trends_z=trends_z,
        finnhub_news=finnhub_news,
        edgar_filings=edgar_filings,
        fred_macro=macro_data,
    )
    news_sentiment_score = sentiment_result.get("Daily_Sentiment_Score", 0.0)
    alternative_data["news_sentiment_score"] = news_sentiment_score

    # 4. Feature engineering with quant alphas
    if not nifty_prices.is_empty():
        try:
            nifty_features = AlphaFeatures(nifty_prices).transform()
        except Exception as e:
            logger.warning(f"AlphaFeatures failed: {e} – using raw prices")
            nifty_features = nifty_prices
    else:
        nifty_features = pl.DataFrame()

    # 5. Run Composite Orchestrator (us_data passes SPX cross-asset prior)
    orchestrator = SignalOrchestrator()
    composite_signal = orchestrator.compute_composite_signal(
        symbol="^NSEI",
        regime_state=regime_state,
        options_data=options_data,
        crypto_data=crypto_data,
        alternative_data=alternative_data,
        macro_data=macro_data,
        price_history=nifty_features,
        us_data=us_data,
    )


    telegram_payloads: list[dict[str, Any]] = []

    if composite_signal is None:
        print("Composite Signal Orchestrator: No trade signal cleared conviction threshold & agreement check.")
        no_trade_output = {
            "status": "NO_TRADE",
            "reason": "No sleeve cleared threshold",
            "confidence": 0.0,
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "regime_state": regime_state,
            "signals_sent": 0,
        }
        
        # Phase 3: Record WATCH to Paper Trader to ensure theoretical_trades gets rows for UI
        paper_trader.record_signal(
            symbol="^NSEI",
            direction="WATCH",
            expected_price=spot_price or 22000.0,
            quantity=0
        )
        
        print("\n================ COMPOSITE SIGNAL RESULT (THE BRAIN) ================")
        print(json.dumps(no_trade_output, indent=2))
        print("=====================================================================\n")

        # Update unrealized PnL and adherence tracking even on NO_TRADE days
        paper_trader.update_unrealized_pnl(symbol="^NSEI", current_close=spot_price or 22000.0)

        end_time = time.time()
        health_monitor.track_latency("full_pipeline", (end_time - start_time) * 1000)
        health_monitor.track_signal_velocity(0)
        health_monitor.generate_health_dashboard({
            "signal_velocity": 0,
            "recent_errors": sum(len(fails) for fails in circuit_breaker.api_failures.values())
        })

        print(json.dumps(no_trade_output, indent=2))
        logger.info("Telegram suppressed NO_TRADE correct")
        return no_trade_output

    # Phase 3: Record to Paper Trader (Only for approved trades)
    paper_trader.record_signal(
        symbol=composite_signal["symbol"],
        direction=composite_signal["direction"],
        expected_price=spot_price or 22000.0,
        quantity=1 # Simplified
    )
    # Also update unrealized P&L
    paper_trader.update_unrealized_pnl(composite_signal["symbol"], spot_price or 22000.0)
    
    # Evaluate Kill Switch AFTER Paper Insert
    if circuit_breaker.evaluate_kill_switch():
        msg_payload = {"Status": "KILL_SWITCH", "Message": "DD > 15% or adherence < 50%"}
        circuit_breaker.send_alert(
            json.dumps(msg_payload),
            lambda msg: asyncio.get_event_loop().create_task(send_telegram_signal(json.loads(msg)))
        )
        return {"status": "HALTED", "reason": "Kill switch triggered after paper insert"}
        
    # Call paper_gate before real execution
    from nexus_astra.backtesting.paper_gate import PaperTradingGate
    gate = PaperTradingGate()
    paper_results = paper_trader.paper_performance_report() if hasattr(paper_trader, 'paper_performance_report') else {}
    gate.go_live_criteria(paper_results)

    # Format and output the final structured signal dict
    print("\n================ COMPOSITE SIGNAL RESULT (THE BRAIN) ================")
    print(json.dumps(composite_signal, indent=2))
    print("=====================================================================\n")

    # Construct standard Telegram signal alert payload
    payload = {
        "Status": "APPROVED",
        "Symbol": composite_signal["symbol"],
        "Signal Type": f"{composite_signal['direction']}_{composite_signal['duration']}",
        "Entry Price": spot_price or 22000.0,
        "Target": (spot_price or 22000.0) * (1.025 if composite_signal["direction"] == "LONG" else 0.975),
        "Stop Loss": (spot_price or 22000.0) * ((1.0 - composite_signal["stop_loss_pct"]/100.0) if composite_signal["direction"] == "LONG" else (1.0 + composite_signal["stop_loss_pct"]/100.0)),
        "Confidence Score": composite_signal["composite_score"],
        "Position Size": composite_signal["position_size_pct"],
        "PCR": pcr,
        "Max Pain": max_pain,
        "Zero Gamma": zero_gamma,
        "Pin Risk Score": pin_risk,
        "Expected Return": composite_signal.get("expected_return_pct", 0.0),
        "Probability": composite_signal.get("confidence", 0.0),
        "Kelly": composite_signal.get("kelly_raw_pct", 0.0),
        "Layer Agreement": composite_signal.get("layer_agreement_count", 0),
        "News Sentiment": alternative_data.get("news_sentiment_score", 0.0),
        "Invalidation": " | ".join(composite_signal.get("invalidation_conditions", [])),
        "Duration": composite_signal.get("duration", "DAYS"),
        "Duration Display": composite_signal.get("duration_display", ""),
        "Duration Days": composite_signal.get("duration_days", 0.0),
        "Duration Theta": composite_signal.get("duration_theta", 0.0),
        "Duration Z-Score": composite_signal.get("duration_z_score", 0.0),
        "Duration GARCH Vol State": composite_signal.get("duration_garch_vol_state", "LOW"),
        "Duration Rule": composite_signal.get("duration_regime_rule", ""),
    }
    telegram_payloads.append(payload)

    # Send Alert using Circuit Breaker (exponential backoff / SMTP fallback)
    circuit_breaker.send_alert(
        json.dumps(payload, indent=2), 
        lambda msg: asyncio.get_event_loop().create_task(send_telegram_signal(json.loads(msg)))
    )

    end_time = time.time()
    
    # Push System Health Metrics
    health_monitor.track_latency("full_pipeline", (end_time - start_time) * 1000)
    health_monitor.track_signal_velocity(len(telegram_payloads))
    health_monitor.generate_health_dashboard({
        "signal_velocity": len(telegram_payloads),
        "recent_errors": sum(len(fails) for fails in circuit_breaker.api_failures.values())
    })

    result = {
        "status": "APPROVED",
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "regime_state": regime_state,
        "signals_sent": len(telegram_payloads),
        "signal": composite_signal,
    }
    print(json.dumps(result, indent=2))
    return result

async def main() -> dict[str, Any] | None:
    health_monitor = SystemHealth()
    circuit_breaker = CircuitBreaker()
    paper_trader = PaperTrader()
    
    # 1. Bootstrap / Daily Data Refresh
    # Check if NIFTY index specifically has data (not just BTC-USD)
    prices_raw = _load_table_as_polars(PricesRaw)
    nifty_raw = prices_raw.filter(pl.col("symbol") == "^NSEI") if not prices_raw.is_empty() and "symbol" in prices_raw.columns else pl.DataFrame()
    
    needs_bootstrap = nifty_raw.is_empty()
    needs_daily_update = False
    if not nifty_raw.is_empty():
        # Check staleness: if latest NIFTY row is > 1 trading day old, refresh
        try:
            latest_date = nifty_raw.select(pl.col("trade_date").max()).item()
            from datetime import date as date_cls
            days_old = (date_cls.today() - latest_date).days if latest_date else 999
            today = date_cls.today()
            is_weekend = today.weekday() in (5, 6)
            now_utc = datetime.now(timezone.utc)
            today_session_closed = now_utc.hour >= 11
            if is_weekend:
                needs_daily_update = days_old > 2
            elif today_session_closed:
                needs_daily_update = days_old >= 1
            else:
                needs_daily_update = days_old > 1
        except Exception:
            needs_daily_update = True

    if needs_bootstrap or needs_daily_update:
        reason = "bootstrap" if needs_bootstrap else f"daily update (data {days_old}d old)"
        logger.info(f"Data refresh triggered: {reason}")
        try:
            from scripts.bootstrap_live import run_bootstrap
            run_bootstrap(period="1mo")
            # Reload after fetch
            prices_raw = _load_table_as_polars(PricesRaw)
        except Exception as e:
            logger.error(f"DATA_FAIL: Live bootstrap failed: {e}")
            try:
                from nexus_astra.data_ingestion.data_fetcher import MarketDataFetcher
                fetcher = MarketDataFetcher()
                await fetcher.fetch_all()
                prices_raw = _load_table_as_polars(PricesRaw)
            except Exception as e2:
                logger.error(f"DATA_FAIL: Secondary fetch also failed: {e2}")
                if needs_bootstrap:
                    return {"status": "DATA_FAIL", "reason": f"Bootstrap failed: {e}"}
            # On daily update failure, continue with existing data


    # 2. Staleness guard (circuit breaker)
    if not circuit_breaker.check_data_staleness(datetime.now()):
        prices_raw = _load_table_as_polars(PricesRaw)
        nifty_check = prices_raw.filter(pl.col("symbol") == "^NSEI") if not prices_raw.is_empty() and "symbol" in prices_raw.columns else pl.DataFrame()
        if nifty_check.is_empty():
            logger.critical("CRITICAL: NIFTY data empty after bootstrap. DATA_FAIL.")
            return {"status": "DATA_FAIL", "reason": "NIFTY data unavailable after bootstrap"}

    # 3. Execute main pipeline with top-level error handling
    try:
        return await pipeline_run(circuit_breaker, health_monitor, paper_trader)
    except Exception as e:
        logger.critical(f"Pipeline fatal failure: {e}", exc_info=True)
        circuit_breaker.log_event("MainPipeline", "CRITICAL", f"Fatal failure: {e}")

        try:
            circuit_breaker.send_alert(f"PIPELINE FAILURE: {e}", lambda m: None)
        except Exception:
            pass
        return {"status": "ERROR", "reason": str(e)}

def _load_table_as_polars(model: Any) -> pl.DataFrame:
    with database_manager.session_scope() as session:
        rows = session.query(model).all()

    if not rows:
        return pl.DataFrame()

    records: list[dict[str, Any]] = []
    for row in rows:
        record = asdict(row) if is_dataclass(row) else row.__dict__.copy()
        record.pop("_sa_instance_state", None)
        records.append(record)

    frame = pl.DataFrame(records)
    if "created_at" in frame.columns:
        frame = frame.drop("created_at")
    return frame

def _latest_macro_vix(frame: pl.DataFrame) -> float:
    if frame.is_empty() or "india_vix" not in frame.columns:
        return 0.0

    sorted_frame = frame.sort("date" if "date" in frame.columns else frame.columns[0], descending=False)
    latest_series = sorted_frame.get_column("india_vix").drop_nulls()
    if latest_series.is_empty():
        return 0.0

    return float(latest_series[-1])

def _standardize_date_column(frame: pl.DataFrame, source_column: str) -> pl.DataFrame:
    if frame.is_empty() or source_column not in frame.columns:
        return frame

    renamed = frame.rename({source_column: "date"})
    if "date" in renamed.columns:
        return renamed

    return frame

if __name__ == "__main__":
    asyncio.run(main())
