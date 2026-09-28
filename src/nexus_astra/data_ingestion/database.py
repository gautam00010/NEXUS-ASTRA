"""SQLite database bootstrap for NEXUS-ASTRA market data storage."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import date, datetime
from pathlib import Path
from threading import Lock
from typing import Generator

from sqlalchemy import Boolean, Date, DateTime, Integer, Numeric, String, UniqueConstraint, create_engine, func, ForeignKey
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker


DATABASE_NAME = "astra_market_data.db"
DATABASE_PATH = Path(__file__).resolve().parents[3] / DATABASE_NAME
DATABASE_URL = f"sqlite:///{DATABASE_PATH.as_posix()}"


class Base(DeclarativeBase):
    """Declarative base for all market data tables."""


class DailyPriceData(Base):
    __tablename__ = "daily_price_data"
    __table_args__ = (
        UniqueConstraint("Symbol", "Date", name="uq_daily_price_symbol_date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column("Symbol", String(32), nullable=False, index=True)
    trade_date: Mapped[date] = mapped_column("Date", Date, nullable=False, index=True)
    open: Mapped[float] = mapped_column("Open", Numeric(18, 6), nullable=False)
    high: Mapped[float] = mapped_column("High", Numeric(18, 6), nullable=False)
    low: Mapped[float] = mapped_column("Low", Numeric(18, 6), nullable=False)
    close: Mapped[float] = mapped_column("Close", Numeric(18, 6), nullable=False)
    adj_close: Mapped[float | None] = mapped_column("AdjClose", Numeric(18, 6), nullable=True)
    volume: Mapped[int] = mapped_column("Volume", Integer, nullable=False)
    vwap: Mapped[float | None] = mapped_column("VWAP", Numeric(18, 6), nullable=True)
    observation_date: Mapped[date | None] = mapped_column("ObservationDate", Date, nullable=True)
    publication_date: Mapped[datetime | None] = mapped_column("PublicationDate", DateTime(timezone=True), nullable=True)
    first_allowed_date: Mapped[date | None] = mapped_column("FirstAllowedDate", Date, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class PricesRaw(Base):
    __tablename__ = "prices_raw"
    __table_args__ = (
        UniqueConstraint("Symbol", "Date", name="uq_prices_raw_symbol_date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column("Symbol", String(32), nullable=False, index=True)
    trade_date: Mapped[date] = mapped_column("Date", Date, nullable=False, index=True)
    open: Mapped[float] = mapped_column("Open", Numeric(18, 6), nullable=False)
    high: Mapped[float] = mapped_column("High", Numeric(18, 6), nullable=False)
    low: Mapped[float] = mapped_column("Low", Numeric(18, 6), nullable=False)
    close: Mapped[float] = mapped_column("Close", Numeric(18, 6), nullable=False)
    adj_close: Mapped[float] = mapped_column("AdjClose", Numeric(18, 6), nullable=False)
    volume: Mapped[int] = mapped_column("Volume", Integer, nullable=False)
    vwap: Mapped[float | None] = mapped_column("VWAP", Numeric(18, 6), nullable=True)
    observation_date: Mapped[date | None] = mapped_column("ObservationDate", Date, nullable=True)
    publication_date: Mapped[datetime | None] = mapped_column("PublicationDate", DateTime(timezone=True), nullable=True)
    first_allowed_date: Mapped[date | None] = mapped_column("FirstAllowedDate", Date, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class CorporateActions(Base):
    __tablename__ = "corporate_actions"
    __table_args__ = (
        UniqueConstraint("Symbol", "Date", "ActionType", name="uq_corporate_actions_symbol_date_type"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column("Symbol", String(32), nullable=False, index=True)
    action_date: Mapped[date] = mapped_column("Date", Date, nullable=False, index=True)
    action_type: Mapped[str] = mapped_column("ActionType", String(32), nullable=False)  # SPLIT, DIVIDEND
    value: Mapped[float] = mapped_column("Value", Numeric(18, 6), nullable=False)
    observation_date: Mapped[date | None] = mapped_column("ObservationDate", Date, nullable=True)
    publication_date: Mapped[datetime | None] = mapped_column("PublicationDate", DateTime(timezone=True), nullable=True)
    first_allowed_date: Mapped[date | None] = mapped_column("FirstAllowedDate", Date, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class InstitutionalFlows(Base):
    __tablename__ = "institutional_flows"
    __table_args__ = (
        UniqueConstraint("Date", name="uq_institutional_flows_date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    flow_date: Mapped[date] = mapped_column("Date", Date, nullable=False, index=True)
    fii_buy: Mapped[float] = mapped_column("FII_Buy", Numeric(18, 6), nullable=False, default=0)
    fii_sell: Mapped[float] = mapped_column("FII_Sell", Numeric(18, 6), nullable=False, default=0)
    dii_buy: Mapped[float] = mapped_column("DII_Buy", Numeric(18, 6), nullable=False, default=0)
    dii_sell: Mapped[float] = mapped_column("DII_Sell", Numeric(18, 6), nullable=False, default=0)
    net_fii: Mapped[float] = mapped_column("Net_FII", Numeric(18, 6), nullable=False, default=0)
    net_dii: Mapped[float] = mapped_column("Net_DII", Numeric(18, 6), nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class MacroRegime(Base):
    __tablename__ = "macro_regime"
    __table_args__ = (
        UniqueConstraint("Date", name="uq_macro_regime_date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    regime_date: Mapped[date] = mapped_column("Date", Date, nullable=False, index=True)
    india_vix: Mapped[float | None] = mapped_column("India_VIX", Numeric(18, 6), nullable=True)
    us_vix: Mapped[float | None] = mapped_column("US_VIX", Numeric(18, 6), nullable=True)
    usd_inr: Mapped[float | None] = mapped_column("USD_INR", Numeric(18, 6), nullable=True)
    brent_crude: Mapped[float | None] = mapped_column("Brent_Crude", Numeric(18, 6), nullable=True)
    macro_regime_score: Mapped[float | None] = mapped_column("Macro_Regime_Score", Numeric(18, 6), nullable=True)
    regime_label: Mapped[str | None] = mapped_column("Regime_Label", String, nullable=True)
    flags: Mapped[str | None] = mapped_column("Flags", String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class CryptoMetrics(Base):
    __tablename__ = "crypto_metrics"
    __table_args__ = (
        UniqueConstraint("Symbol", "Date", name="uq_crypto_metrics_symbol_date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column("Symbol", String(32), nullable=False, index=True)
    date: Mapped[datetime] = mapped_column("Date", DateTime, nullable=False, index=True)
    funding_rate: Mapped[float] = mapped_column("FundingRate", Numeric(18, 6), nullable=False)
    oi_change_24h: Mapped[float] = mapped_column("OI_Change_24h", Numeric(18, 6), nullable=False)
    oi_change_7d: Mapped[float] = mapped_column("OI_Change_7d", Numeric(18, 6), nullable=False)
    liquidation_levels: Mapped[str] = mapped_column("Liquidation_Levels", String, nullable=False)
    flags: Mapped[str | None] = mapped_column("Flags", String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class AlternativeData(Base):
    __tablename__ = "alternative_data"
    __table_args__ = (
        UniqueConstraint("Date", name="uq_alternative_data_date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    date: Mapped[date] = mapped_column("Date", Date, nullable=False, index=True)
    retail_fear_zscore: Mapped[float] = mapped_column("Retail_Fear_ZScore", Numeric(18, 6), nullable=False)
    retail_greed_zscore: Mapped[float] = mapped_column("Retail_Greed_ZScore", Numeric(18, 6), nullable=False)
    crypto_interest_zscore: Mapped[float] = mapped_column("Crypto_Interest_ZScore", Numeric(18, 6), nullable=False)
    raw_scores_json: Mapped[str] = mapped_column("Raw_Scores_JSON", String, nullable=False)
    flags: Mapped[str | None] = mapped_column("Flags", String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class NewsSentimentCache(Base):
    __tablename__ = "news_sentiment_cache"
    __table_args__ = (
        UniqueConstraint("Date", name="uq_news_sentiment_cache_date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    date: Mapped[date] = mapped_column("Date", Date, nullable=False, index=True)
    daily_sentiment_score: Mapped[float] = mapped_column("Daily_Sentiment_Score", Numeric(18, 6), nullable=False)
    raw_headlines_json: Mapped[str] = mapped_column("Raw_Headlines_JSON", String, nullable=False)
    flags: Mapped[str | None] = mapped_column("Flags", String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class BacktestResults(Base):
    __tablename__ = "backtest_results"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column("Symbol", String(32), nullable=False, index=True)
    start_date: Mapped[date] = mapped_column("StartDate", Date, nullable=False)
    end_date: Mapped[date] = mapped_column("EndDate", Date, nullable=False)
    sharpe_ratio: Mapped[float] = mapped_column("SharpeRatio", Numeric(18, 6), nullable=False)
    max_drawdown: Mapped[float] = mapped_column("MaxDrawdown", Numeric(18, 6), nullable=False)
    win_rate: Mapped[float] = mapped_column("WinRate", Numeric(18, 6), nullable=False)
    profit_factor: Mapped[float] = mapped_column("ProfitFactor", Numeric(18, 6), nullable=False)
    expectancy: Mapped[float] = mapped_column("Expectancy", Numeric(18, 6), nullable=False)
    calmar_ratio: Mapped[float] = mapped_column("CalmarRatio", Numeric(18, 6), nullable=False)
    monte_carlo_var_95: Mapped[float] = mapped_column("MonteCarloVaR95", Numeric(18, 6), nullable=False)
    prob_profitable_year: Mapped[float] = mapped_column("ProbProfitableYear", Numeric(18, 6), nullable=False)
    median_terminal_wealth: Mapped[float] = mapped_column("MedianTerminalWealth", Numeric(18, 6), nullable=False)
    regime_dependent_risk: Mapped[bool] = mapped_column("RegimeDependentRisk", Integer, nullable=False, default=0) # boolean via Integer
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class TheoreticalTrades(Base):
    __tablename__ = "theoretical_trades"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    signal_id: Mapped[str] = mapped_column("SignalId", String(64), nullable=False)
    freeze_ts: Mapped[datetime] = mapped_column("FreezeTs", DateTime(timezone=True), nullable=False)
    symbol: Mapped[str] = mapped_column("Symbol", String(32), nullable=False, index=True)
    direction: Mapped[str] = mapped_column("Direction", String(16), nullable=False)
    theoretical_entry: Mapped[float] = mapped_column("TheoreticalEntry", Numeric(18, 6), nullable=False)
    size: Mapped[float] = mapped_column("Size", Numeric(18, 6), nullable=False)
    cost_hash: Mapped[str] = mapped_column("CostHash", String(64), nullable=False)
    code_hash: Mapped[str] = mapped_column("CodeHash", String(64), nullable=False)
    git_sha: Mapped[str] = mapped_column("GitSha", String(64), nullable=False)
    observation_date: Mapped[date | None] = mapped_column("ObservationDate", Date, nullable=True)
    publication_date: Mapped[datetime | None] = mapped_column("PublicationDate", DateTime(timezone=True), nullable=True)
    first_allowed_date: Mapped[date | None] = mapped_column("FirstAllowedDate", Date, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

class ActualFills(Base):
    __tablename__ = "actual_fills"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    theoretical_id: Mapped[int] = mapped_column(ForeignKey("theoretical_trades.id"), nullable=False)
    actual_price: Mapped[float] = mapped_column("ActualPrice", Numeric(18, 6), nullable=False)
    actual_time: Mapped[datetime] = mapped_column("ActualTime", DateTime(timezone=True), nullable=False)
    slippage_actual: Mapped[float] = mapped_column("SlippageActual", Numeric(18, 6), nullable=False)
    delay_mins: Mapped[float] = mapped_column("DelayMins", Numeric(18, 6), nullable=False)
    observation_date: Mapped[date | None] = mapped_column("ObservationDate", Date, nullable=True)
    publication_date: Mapped[datetime | None] = mapped_column("PublicationDate", DateTime(timezone=True), nullable=True)
    first_allowed_date: Mapped[date | None] = mapped_column("FirstAllowedDate", Date, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

class AdherenceDaily(Base):
    __tablename__ = "adherence_daily"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    date: Mapped[date] = mapped_column("Date", Date, nullable=False, index=True)
    theoretical_pnl: Mapped[float] = mapped_column("TheoreticalPnL", Numeric(18, 6), nullable=False)
    actual_pnl: Mapped[float] = mapped_column("ActualPnL", Numeric(18, 6), nullable=False)
    tracking_error: Mapped[float] = mapped_column("TrackingError", Numeric(18, 6), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class SystemLogs(Base):
    __tablename__ = "system_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    timestamp: Mapped[datetime] = mapped_column("Timestamp", DateTime(timezone=True), nullable=False, index=True)
    component: Mapped[str] = mapped_column("Component", String(64), nullable=False)
    level: Mapped[str] = mapped_column("Level", String(32), nullable=False) # INFO, WARNING, ERROR, CRITICAL
    message: Mapped[str] = mapped_column("Message", String, nullable=False)
    details_json: Mapped[str | None] = mapped_column("DetailsJSON", String, nullable=True)


class SectorMetrics(Base):
    __tablename__ = "sector_metrics"
    __table_args__ = (
        UniqueConstraint("Sector", "Date", name="uq_sector_metrics_sector_date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    sector: Mapped[str] = mapped_column("Sector", String(64), nullable=False, index=True)
    date: Mapped[date] = mapped_column("Date", Date, nullable=False, index=True)
    relative_strength_20d: Mapped[float] = mapped_column("RelativeStrength20d", Numeric(18, 6), nullable=False)
    classification: Mapped[str] = mapped_column("Classification", String(32), nullable=False) # LEADER, LAGGARD, NEUTRAL
    flags: Mapped[str | None] = mapped_column("Flags", String, nullable=True) # STRONG_TREND, CAPITULATION_SETUP
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class EventRiskLog(Base):
    __tablename__ = "event_risk_log"
    __table_args__ = (
        UniqueConstraint("Symbol", "Date", "EventName", name="uq_event_risk_log_symbol_date_event"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column("Symbol", String(32), nullable=False, index=True)
    date: Mapped[date] = mapped_column("Date", Date, nullable=False, index=True)
    event_name: Mapped[str] = mapped_column("EventName", String(128), nullable=False)
    risk_score: Mapped[float] = mapped_column("RiskScore", Numeric(18, 6), nullable=False)
    trading_restriction: Mapped[str | None] = mapped_column("TradingRestriction", String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class DarkPoolMetrics(Base):
    __tablename__ = "dark_pool_metrics"
    __table_args__ = (
        UniqueConstraint("Symbol", "Date", name="uq_dark_pool_metrics_symbol_date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column("Symbol", String(32), nullable=False, index=True)
    date: Mapped[date] = mapped_column("Date", Date, nullable=False, index=True)
    institutional_pressure_score: Mapped[float] = mapped_column("InstPressureScore", Numeric(18, 6), nullable=False)
    block_deal_premium: Mapped[float] = mapped_column("BlockDealPremium", Numeric(18, 6), nullable=False)
    delivery_percentage: Mapped[float] = mapped_column("DeliveryPercentage", Numeric(18, 6), nullable=False)
    flags: Mapped[str | None] = mapped_column("Flags", String, nullable=True) # STRONG_CONVICTION
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class TradeLog(Base):
    __tablename__ = "trade_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column("Symbol", String(32), nullable=False)
    signal_type: Mapped[str] = mapped_column("SignalType", String(64), nullable=False)
    regime: Mapped[str] = mapped_column("Regime", String(32), nullable=False)
    entry_date: Mapped[date] = mapped_column("EntryDate", Date, nullable=False)
    exit_date: Mapped[date] = mapped_column("ExitDate", Date, nullable=False)
    pnl_pct: Mapped[float] = mapped_column("PnLPct", Numeric(18, 6), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class OptimalFHistory(Base):
    __tablename__ = "optimal_f_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    date: Mapped[date] = mapped_column("Date", Date, nullable=False, index=True)
    signal_type: Mapped[str] = mapped_column("SignalType", String(64), nullable=False)
    optimal_f: Mapped[float] = mapped_column("OptimalF", Numeric(18, 6), nullable=False)
    conservative_f: Mapped[float] = mapped_column("ConservativeF", Numeric(18, 6), nullable=False)
    median_f: Mapped[float] = mapped_column("MedianF", Numeric(18, 6), nullable=False)
    aggressive_f: Mapped[float] = mapped_column("AggressiveF", Numeric(18, 6), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class BayesianPriors(Base):
    __tablename__ = "bayesian_priors"
    __table_args__ = (
        UniqueConstraint("SignalType", "DataFeature", "FeatureState", name="uq_bayesian_priors"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    signal_type: Mapped[str] = mapped_column("SignalType", String(64), nullable=False)
    data_feature: Mapped[str] = mapped_column("DataFeature", String(64), nullable=False)
    feature_state: Mapped[str] = mapped_column("FeatureState", String(64), nullable=False)
    likelihood: Mapped[float] = mapped_column("Likelihood", Numeric(18, 6), nullable=False)
    marginal_prob: Mapped[float] = mapped_column("MarginalProb", Numeric(18, 6), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class ActiveSignalState(Base):
    __tablename__ = "active_signal_state"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    signal_id: Mapped[str] = mapped_column("SignalId", String(64), nullable=False, unique=True)
    symbol: Mapped[str] = mapped_column("Symbol", String(32), nullable=False)
    signal_type: Mapped[str] = mapped_column("SignalType", String(64), nullable=False)
    current_confidence: Mapped[float] = mapped_column("CurrentConfidence", Numeric(18, 6), nullable=False)
    status: Mapped[str] = mapped_column("Status", String(32), nullable=False) # ACTIVE, CANCELLED, CLOSED
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class DynamicWeights(Base):
    __tablename__ = "dynamic_weights"
    __table_args__ = (
        UniqueConstraint("Date", "SignalType", name="uq_dynamic_weights_date_signal"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    date: Mapped[date] = mapped_column("Date", Date, nullable=False, index=True)
    signal_type: Mapped[str] = mapped_column("SignalType", String(64), nullable=False)
    weight: Mapped[float] = mapped_column("Weight", Numeric(18, 6), nullable=False)
    correlation: Mapped[float | None] = mapped_column("Correlation", Numeric(18, 6), nullable=True)
    accuracy: Mapped[float | None] = mapped_column("Accuracy", Numeric(18, 6), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class BaseRateAnalytics(Base):
    __tablename__ = "base_rate_analytics"
    __table_args__ = (
        UniqueConstraint("Date", "SignalType", name="uq_base_rate_date_signal"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    date: Mapped[date] = mapped_column("Date", Date, nullable=False, index=True)
    signal_type: Mapped[str] = mapped_column("SignalType", String(64), nullable=False)
    base_rate: Mapped[float] = mapped_column("BaseRate", Numeric(18, 6), nullable=False)
    sensitivity: Mapped[float] = mapped_column("Sensitivity", Numeric(18, 6), nullable=False)
    specificity: Mapped[float] = mapped_column("Specificity", Numeric(18, 6), nullable=False)
    ppv: Mapped[float] = mapped_column("PPV", Numeric(18, 6), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class IndexConstituents(Base):
    __tablename__ = "index_constituents"
    __table_args__ = (
        UniqueConstraint("IndexName", "Symbol", "EntryDate", name="uq_index_constituents"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    index_name: Mapped[str] = mapped_column("IndexName", String(32), nullable=False)
    symbol: Mapped[str] = mapped_column("Symbol", String(32), nullable=False, index=True)
    entry_date: Mapped[date] = mapped_column("EntryDate", Date, nullable=False, index=True)
    exit_date: Mapped[date | None] = mapped_column("ExitDate", Date, nullable=True)
    is_delisted: Mapped[bool] = mapped_column("IsDelisted", Boolean, nullable=False, default=False)
    observation_date: Mapped[date | None] = mapped_column("ObservationDate", Date, nullable=True)
    publication_date: Mapped[datetime | None] = mapped_column("PublicationDate", DateTime(timezone=True), nullable=True)
    first_allowed_date: Mapped[date | None] = mapped_column("FirstAllowedDate", Date, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class SignalDiagnostics(Base):
    __tablename__ = "signal_diagnostics"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    date: Mapped[date] = mapped_column("Date", Date, nullable=False, index=True)
    diagnostic_type: Mapped[str] = mapped_column("DiagnosticType", String(64), nullable=False)
    signal_type: Mapped[str] = mapped_column("SignalType", String(64), nullable=False)
    metric_value: Mapped[float] = mapped_column("MetricValue", Numeric(18, 6), nullable=False)
    details: Mapped[str | None] = mapped_column("Details", String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class TailRiskParams(Base):
    __tablename__ = "tail_risk_params"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    date: Mapped[date] = mapped_column("Date", Date, nullable=False, index=True)
    regime: Mapped[str] = mapped_column("Regime", String(32), nullable=False)
    df: Mapped[float] = mapped_column("DF", Numeric(18, 6), nullable=False)
    loc: Mapped[float] = mapped_column("Loc", Numeric(18, 6), nullable=False)
    scale: Mapped[float] = mapped_column("Scale", Numeric(18, 6), nullable=False)
    var_99: Mapped[float] = mapped_column("VaR99", Numeric(18, 6), nullable=False)
    normal_var_99: Mapped[float] = mapped_column("NormalVaR99", Numeric(18, 6), nullable=False)
    underestimation_pct: Mapped[float] = mapped_column("UnderestimationPct", Numeric(18, 6), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class PsychologyLog(Base):
    __tablename__ = "psychology_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    date: Mapped[date] = mapped_column("Date", Date, nullable=False, index=True)
    log_type: Mapped[str] = mapped_column("LogType", String(64), nullable=False)
    signal_id: Mapped[str | None] = mapped_column("SignalId", String(64), nullable=True)
    metric_value: Mapped[float | None] = mapped_column("MetricValue", Numeric(18, 6), nullable=True)
    details: Mapped[str | None] = mapped_column("Details", String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class AutoExitPlan(Base):
    __tablename__ = "auto_exit_plan"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    signal_id: Mapped[str] = mapped_column("SignalId", String(64), nullable=False, unique=True)
    symbol: Mapped[str] = mapped_column("Symbol", String(32), nullable=False)
    entry_price: Mapped[float] = mapped_column("EntryPrice", Numeric(18, 6), nullable=False)
    stop_loss: Mapped[float] = mapped_column("StopLoss", Numeric(18, 6), nullable=False)
    target_1: Mapped[float] = mapped_column("Target1", Numeric(18, 6), nullable=False)
    target_2: Mapped[float] = mapped_column("Target2", Numeric(18, 6), nullable=False)
    target_3: Mapped[float] = mapped_column("Target3", Numeric(18, 6), nullable=False)
    time_stop_date: Mapped[date] = mapped_column("TimeStopDate", Date, nullable=False)
    status: Mapped[str] = mapped_column("Status", String(32), nullable=False, default="ACTIVE")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class InformedFlowMetrics(Base):
    __tablename__ = "informed_flow_metrics"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    date: Mapped[date] = mapped_column("Date", Date, nullable=False, index=True)
    symbol: Mapped[str] = mapped_column("Symbol", String(32), nullable=False, index=True)
    lambda_value: Mapped[float] = mapped_column("LambdaValue", Numeric(18, 8), nullable=False)
    is_informed_detected: Mapped[bool] = mapped_column("IsInformedDetected", Boolean, nullable=False, default=False)
    order_flow_imbalance: Mapped[float] = mapped_column("OrderFlowImbalance", Numeric(18, 6), nullable=False)
    strong_buying: Mapped[bool] = mapped_column("StrongBuying", Boolean, nullable=False, default=False)
    block_deal_impact: Mapped[str | None] = mapped_column("BlockDealImpact", String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class ReflexivityState(Base):
    __tablename__ = "reflexivity_state"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    date: Mapped[date] = mapped_column("Date", Date, nullable=False, index=True)
    metric_name: Mapped[str] = mapped_column("MetricName", String(32), nullable=False)
    value: Mapped[float] = mapped_column("Value", Numeric(18, 6), nullable=False)
    first_derivative: Mapped[float] = mapped_column("FirstDerivative", Numeric(18, 6), nullable=False)
    second_derivative: Mapped[float] = mapped_column("SecondDerivative", Numeric(18, 6), nullable=False)
    state: Mapped[str] = mapped_column("State", String(32), nullable=False)
    reflexivity_score: Mapped[float] = mapped_column("ReflexivityScore", Numeric(18, 6), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class AdaptiveRegime(Base):
    __tablename__ = "adaptive_regime"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    date: Mapped[date] = mapped_column("Date", Date, nullable=False, index=True)
    er_value: Mapped[float] = mapped_column("ErValue", Numeric(18, 6), nullable=False)
    er_moving_avg: Mapped[float] = mapped_column("ErMovingAvg", Numeric(18, 6), nullable=False)
    strategy_bias: Mapped[str] = mapped_column("StrategyBias", String(32), nullable=False)
    size_multiplier: Mapped[float] = mapped_column("SizeMultiplier", Numeric(18, 6), nullable=False)
    inefficiency_flag: Mapped[bool] = mapped_column("InefficiencyFlag", Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class RiskParityAllocations(Base):
    __tablename__ = "risk_parity_allocations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    date: Mapped[date] = mapped_column("Date", Date, nullable=False, index=True)
    symbol: Mapped[str] = mapped_column("Symbol", String(32), nullable=False)
    volatility: Mapped[float] = mapped_column("Volatility", Numeric(18, 6), nullable=False)
    allocation_weight: Mapped[float] = mapped_column("AllocationWeight", Numeric(18, 6), nullable=False)
    target_vol_contribution: Mapped[float] = mapped_column("TargetVolContribution", Numeric(18, 6), nullable=False)
    is_rebalance_triggered: Mapped[bool] = mapped_column("IsRebalanceTriggered", Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class RegimeStrategies(Base):
    __tablename__ = "regime_strategies"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    date: Mapped[date] = mapped_column("Date", Date, nullable=False, index=True)
    regime_name: Mapped[str] = mapped_column("RegimeName", String(64), nullable=False)
    momentum_weight: Mapped[float] = mapped_column("MomentumWeight", Numeric(18, 6), nullable=False)
    mean_reversion_weight: Mapped[float] = mapped_column("MeanReversionWeight", Numeric(18, 6), nullable=False)
    contrarian_weight: Mapped[float] = mapped_column("ContrarianWeight", Numeric(18, 6), nullable=False)
    cash_weight: Mapped[float] = mapped_column("CashWeight", Numeric(18, 6), nullable=False)
    size_multiplier: Mapped[float] = mapped_column("SizeMultiplier", Numeric(18, 6), nullable=False, default=1.0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class CalendarAlpha(Base):
    __tablename__ = "calendar_alpha"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    date: Mapped[date] = mapped_column("Date", Date, nullable=False, index=True)
    sip_inflow_cr: Mapped[float] = mapped_column("SipInflowCr", Numeric(18, 6), nullable=False)
    is_bid_week_1: Mapped[bool] = mapped_column("IsBidWeek1", Boolean, nullable=False, default=False)
    is_bid_week_4: Mapped[bool] = mapped_column("IsBidWeek4", Boolean, nullable=False, default=False)
    midcap_boost: Mapped[bool] = mapped_column("MidcapBoost", Boolean, nullable=False, default=False)
    smallcap_boost: Mapped[bool] = mapped_column("SmallcapBoost", Boolean, nullable=False, default=False)
    slowdown_caution: Mapped[bool] = mapped_column("SlowdownCaution", Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class MSCICalendar(Base):
    __tablename__ = "msci_calendar"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    date: Mapped[date] = mapped_column("Date", Date, nullable=False, index=True)
    announcement_date: Mapped[date] = mapped_column("AnnouncementDate", Date, nullable=False)
    effective_date: Mapped[date] = mapped_column("EffectiveDate", Date, nullable=False)
    symbol: Mapped[str] = mapped_column("Symbol", String(32), nullable=False)
    action_type: Mapped[str] = mapped_column("ActionType", String(32), nullable=False)
    target_weight: Mapped[float] = mapped_column("TargetWeight", Numeric(18, 6), nullable=False)
    trade_signal: Mapped[str] = mapped_column("TradeSignal", String(64), nullable=False)
    performance_result: Mapped[float | None] = mapped_column("PerformanceResult", Numeric(18, 6), nullable=True)
    edge_decaying: Mapped[bool] = mapped_column("EdgeDecaying", Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class EventCalendar(Base):
    __tablename__ = "event_calendar"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    date: Mapped[date] = mapped_column("Date", Date, nullable=False, index=True)
    event_type: Mapped[str] = mapped_column("EventType", String(32), nullable=False)
    proximity_flag: Mapped[str] = mapped_column("ProximityFlag", String(64), nullable=False)
    sector_rotation_bias: Mapped[str | None] = mapped_column("SectorRotationBias", String(128), nullable=True)
    historical_match_flag: Mapped[bool] = mapped_column("HistoricalMatchFlag", Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class CarryRegime(Base):
    __tablename__ = "carry_regime"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    date: Mapped[date] = mapped_column("Date", Date, nullable=False, index=True)
    fed_cycle: Mapped[str] = mapped_column("FedCycle", String(32), nullable=False)
    dxy_regime: Mapped[str] = mapped_column("DxyRegime", String(32), nullable=False)
    us10y_trend: Mapped[str] = mapped_column("Us10yTrend", String(32), nullable=False)
    carry_score: Mapped[float] = mapped_column("CarryScore", Numeric(18, 6), nullable=False)
    duration_modifier: Mapped[float] = mapped_column("DurationModifier", Numeric(18, 6), nullable=False, default=1.0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class SignalPerformance(Base):
    __tablename__ = "signal_performance"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    signal_id: Mapped[str] = mapped_column("SignalId", String(64), unique=True, index=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column("CreatedAt", DateTime(timezone=True), nullable=False)
    signal_type: Mapped[str] = mapped_column("SignalType", String(64), nullable=False)
    composite_confidence: Mapped[float] = mapped_column("CompositeConfidence", Numeric(18, 6), nullable=False)
    expected_return: Mapped[float] = mapped_column("ExpectedReturn", Numeric(18, 6), nullable=False)
    expected_duration: Mapped[int] = mapped_column("ExpectedDuration", Integer, nullable=False)
    predicted_direction: Mapped[str] = mapped_column("PredictedDirection", String(16), nullable=False)
    sub_signals: Mapped[str | None] = mapped_column("SubSignals", String, nullable=True) # JSON string
    regime_state: Mapped[str | None] = mapped_column("RegimeState", String(64), nullable=True)
    carry_score: Mapped[float | None] = mapped_column("CarryScore", Numeric(18, 6), nullable=True)
    
    is_closed: Mapped[bool] = mapped_column("IsClosed", Boolean, nullable=False, default=False)
    actual_return: Mapped[float | None] = mapped_column("ActualReturn", Numeric(18, 6), nullable=True)
    holding_period: Mapped[int | None] = mapped_column("HoldingPeriod", Integer, nullable=True)
    slippage: Mapped[float | None] = mapped_column("Slippage", Numeric(18, 6), nullable=True)
    vs_expected_return: Mapped[float | None] = mapped_column("VsExpectedReturn", Numeric(18, 6), nullable=True)
    is_win: Mapped[bool | None] = mapped_column("IsWin", Boolean, nullable=True)
    max_adverse_excursion: Mapped[float | None] = mapped_column("MaxAdverseExcursion", Numeric(18, 6), nullable=True)


class PaperTradingGateState(Base):
    __tablename__ = "paper_trading_gate_state"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    date: Mapped[date] = mapped_column("Date", Date, nullable=False, index=True)
    stage: Mapped[str] = mapped_column("Stage", String(32), nullable=False)
    sharpe_ratio: Mapped[float] = mapped_column("SharpeRatio", Numeric(18, 6), nullable=False)
    max_drawdown: Mapped[float] = mapped_column("MaxDrawdown", Numeric(18, 6), nullable=False)
    capital_deployment_pct: Mapped[float] = mapped_column("CapitalDeploymentPct", Numeric(18, 6), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class DatabaseManager:
    """Singleton manager for the SQLite engine and sessions."""

    _instance: DatabaseManager | None = None
    _lock: Lock = Lock()

    def __new__(cls) -> DatabaseManager:
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self) -> None:
        if getattr(self, "_initialized", False):
            return

        DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
        self.engine = create_engine(
            DATABASE_URL,
            connect_args={"check_same_thread": False},
            future=True,
            pool_pre_ping=True,
        )
        self.SessionLocal = sessionmaker(bind=self.engine, autoflush=False, autocommit=False, expire_on_commit=False)
        self._initialized = True

    def create_tables(self) -> None:
        Base.metadata.create_all(bind=self.engine)

    def get_session(self) -> Session:
        return self.SessionLocal()

    @contextmanager
    def session_scope(self) -> Generator[Session, None, None]:
        session = self.get_session()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()


database_manager = DatabaseManager()


def initialize_database() -> None:
    """Create the SQLite database and all declared tables."""

    database_manager.create_tables()


if __name__ == "__main__":
    initialize_database()
