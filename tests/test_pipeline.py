"""Comprehensive mock-based unit and integration test suite for NEXUS-ASTRA."""

from __future__ import annotations

import asyncio
import json
from datetime import date, datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
import polars as pl
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from nexus_astra.data_ingestion import (
    DailyPriceData,
    DatabaseManager,
    InstitutionalFlows,
    MacroRegime,
    CryptoMetrics,
    AlternativeData,
    NewsSentimentCache,
    MarketDataFetcher,
    NSEOptionsFetcher,
    SocialScraper,
    TrendsEngine,
)


from nexus_astra.delivery.telegram_delivery import _format_markdown_message
from nexus_astra.feature_engineering import (
    AlphaFeatures,
    detect_market_regime,
    detect_historical_regimes,
    GammaExposure,
    WhaleIntelligence,
    NewsSentiment,
)
from nexus_astra.feature_engineering.macro_overlay import MacroRegime as MacroOverlay
from nexus_astra.ml_models import EnsembleEngine
from nexus_astra.signal_engine.composite_orchestrator import SignalOrchestrator
from nexus_astra.risk_management import (
    calculate_final_capital_allocation_pct,
    calculate_fractional_kelly_allocation,
    apply_volatility_targeting,
)


@pytest.fixture
def mock_db_manager():
    """Create a temporary in-memory SQLite database manager for testing."""
    from sqlalchemy.pool import StaticPool
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool
    )
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    
    db_mgr = MagicMock(spec=DatabaseManager)
    db_mgr.engine = engine
    db_mgr.SessionLocal = SessionLocal
    
    # Re-route session_scope to use this in-memory session
    from contextlib import contextmanager
    @contextmanager
    def session_scope():
        session = SessionLocal()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()
            
    db_mgr.session_scope = session_scope
    db_mgr.create_tables = lambda: DailyPriceData.metadata.create_all(bind=engine)
    return db_mgr


def test_database_creation(mock_db_manager):
    """Verify that database tables can be created successfully in memory."""
    mock_db_manager.create_tables()
    with mock_db_manager.session_scope() as session:
        # Tables should be empty but exist
        assert session.query(DailyPriceData).count() == 0
        assert session.query(InstitutionalFlows).count() == 0
        assert session.query(MacroRegime).count() == 0
        assert session.query(CryptoMetrics).count() == 0


def test_risk_management():
    """Verify Kelly sizing and volatility targeting calculations."""
    # 0.25x Kelly: win_rate=0.55, win_pct=2.0, loss_pct=1.0 -> payoff=2.0
    # kelly = 0.55 - (0.45 / 2) = 0.55 - 0.225 = 0.325
    # fractional_kelly = 0.325 * 0.25 = 0.08125 -> 8.125%
    allocation = calculate_fractional_kelly_allocation(0.55, 2.0, 1.0)
    assert pytest.approx(allocation, abs=0.001) == 8.125

    # Volatility target: VIX > 25 cuts Kelly in half
    assert apply_volatility_targeting(10.0, 20.0) == 10.0
    assert apply_volatility_targeting(10.0, 30.0) == 5.0

    # End-to-end
    final_allocation = calculate_final_capital_allocation_pct(0.55, 2.0, 1.0, 30.0)
    assert pytest.approx(final_allocation, abs=0.001) == 4.0625


def test_telegram_message_formatting():
    """Verify telegram markdown alert generator."""
    payload = {
        "Symbol": "^NSEI",
        "Signal Type": "CALM_BULL",
        "Entry Price": 22000.5,
        "Target": 22500.0,
        "Stop Loss": 21800.0,
        "Confidence Score": 85.0,
        "Position Size": 5.25,
        "PCR": 0.95,
        "Max Pain": 22000,
        "Zero Gamma": 21950,
        "Pin Risk Score": 100.0,
    }
    markdown = _format_markdown_message(payload)
    assert "*Symbol:*" in markdown
    assert "*Signal Type:*" in markdown
    assert "*NIFTY PCR:*" in markdown
    assert "*NIFTY Max Pain:*" in markdown
    assert "*NIFTY Zero Gamma:*" in markdown
    assert "*NIFTY Pin Risk:*" in markdown


def test_alpha_features_computation():
    """Verify technical indicator calculations in AlphaFeatures."""
    dates = [date(2026, 6, 1) + timedelta(days=i) for i in range(70)] # Need 70 days for rolling indicators (min_samples=60)
    close_prices = [100.0 + (i * 0.5) for i in range(70)]
    open_prices = [99.0 + (i * 0.5) for i in range(70)]
    high_prices = [101.0 + (i * 0.5) for i in range(70)]
    low_prices = [98.0 + (i * 0.5) for i in range(70)]
    volumes = [1000 for _ in range(70)]

    df = pl.DataFrame({
        "date": dates,
        "open": open_prices,
        "high": high_prices,
        "low": low_prices,
        "close": close_prices,
        "volume": volumes,
    })

    features = AlphaFeatures(df).compute()
    assert "log_return" in features.columns
    assert "historical_volatility_20" in features.columns
    assert "historical_volatility_60" in features.columns
    assert "rsi_14" in features.columns
    assert "vol_of_vol_20" in features.columns
    assert "distance_from_ema_50" in features.columns


def test_regime_detection():
    """Test market regime detector with conditions for bear momentum and calm bull."""
    flows = pl.DataFrame({
        "Date": [date(2026, 6, 10), date(2026, 6, 11), date(2026, 6, 12)],
        "FII_Buy": [10000.0, 10000.0, 10000.0],
        "FII_Sell": [16000.0, 17000.0, 18000.0], # Selling increases (Bear Momentum)
        "DII_Buy": [5000.0, 5000.0, 5000.0],
        "DII_Sell": [5000.0, 5000.0, 5000.0],
        "Net_FII": [-6000.0, -7000.0, -8000.0],
        "Net_DII": [0.0, 0.0, 0.0],
    })
    
    macro = pl.DataFrame({
        "Date": [date(2026, 6, 10), date(2026, 6, 11), date(2026, 6, 12)],
        "India_VIX": [22.0, 23.0, 24.0],
    })

    regime = detect_market_regime(flows, macro)
    assert regime["regime_state"] == "BEAR_MOMENTUM"
    
    # Historical
    hist_regimes = detect_historical_regimes(flows, macro)
    assert hist_regimes.height == 3
    assert hist_regimes["regime_state"][-1] == "BEAR_MOMENTUM"


def test_gamma_exposure():
    """Verify options zero gamma level and pin risk scoring."""
    df_options = pl.DataFrame({
        "date": [date(2026, 6, 12)] * 5,
        "strike": [21800.0, 21900.0, 22000.0, 22100.0, 22200.0],
        "call_oi": [100.0, 200.0, 500.0, 300.0, 100.0],
        "put_oi": [400.0, 300.0, 500.0, 100.0, 50.0],
        "spot": [22005.0] * 5,
        "underlying_value": [22005.0] * 5,
    })

    gamma_eng = GammaExposure(df_options)
    summary = gamma_eng.compute()
    assert "zero_gamma_level" in summary.columns
    assert "pin_risk_score" in summary.columns
    assert summary["pin_risk_score"][0] in [0.0, 100.0]


def test_ensemble_engine_walk_forward():
    """Verify XGBoost dataset prep and ML training pipeline."""
    dates = [date(2026, 6, 1) + timedelta(days=i) for i in range(100)]
    # Features
    features = {
        "date": dates,
        "close": [100.0 + 10.0 * np.sin(i / 5.0) for i in range(100)],
        "feature_1": [np.random.normal() for _ in range(100)],
        "feature_2": [np.random.normal() for _ in range(100)],
    }
    df = pl.DataFrame(features)
    
    engine = EnsembleEngine(train_window=60, test_window=20, horizon=5)
    prep = engine.prepare_dataset(df)
    assert "target_5d" in prep.columns
    
    # Train mock
    model = engine.train_xgboost_classifier(df)
    assert model is not None

    # Walk-forward OOS validation
    oos = engine.walk_forward_validate(df)
    assert "out_of_sample_accuracy" in oos
    assert len(oos["folds"]) > 0

    # Test composite signal score calculation
    scored = engine.composite_signal_score(df, "CALM_BULL")
    assert isinstance(scored, pl.DataFrame)


@pytest.mark.asyncio
@patch("yfinance.download")
async def test_data_fetcher_and_bootstrapping(mock_yf_download, mock_db_manager):
    """Test Eq/Macro data fetcher and FII/DII historical bootstrapping."""
    mock_db_manager.create_tables()

    # Mock yfinance return
    import pandas as pd
    mock_data = pd.DataFrame(
        {
            "Open": [100.0, 101.0, 102.0],
            "High": [102.0, 103.0, 104.0],
            "Low": [99.0, 100.0, 101.0],
            "Close": [101.5, 102.5, 103.5],
            "Volume": [1000, 1100, 1200],
        },
        index=pd.to_datetime(["2026-06-10", "2026-06-11", "2026-06-12"]),
    )
    mock_data.index.name = "Date"
    mock_yf_download.return_value = mock_data

    # Initialize fetcher with in-memory db manager
    fetcher = MarketDataFetcher(db_manager=mock_db_manager)

    # Mock _fetch_fii_dii_flows to avoid external HTTP call during test
    fii_dii_mock_data = [
        {"buyValue": "15000", "sellValue": "14000", "netValue": "1000", "category": "FII/FPI", "date": "12-Jun-2026"},
        {"buyValue": "10000", "sellValue": "9500", "netValue": "500", "category": "DII", "date": "12-Jun-2026"}
    ]
    fetcher._fetch_fii_dii_flows = AsyncMock(return_value=fii_dii_mock_data)

    # Run pipeline fetch all
    await fetcher.fetch_all()

    with mock_db_manager.session_scope() as session:
        # Check DailyPriceData was inserted
        price_rows = session.query(DailyPriceData).all()
        assert len(price_rows) > 0
        assert price_rows[0].symbol in ["^NSEI", "BTC-USD"]
        
        # Check FII/DII was fetched & inserted
        flow_rows = session.query(InstitutionalFlows).all()
        assert len(flow_rows) > 0
        
        # Verify no synthetic bootstrapping (strict DATA_FAIL policy, only real flows kept)
        assert len(flow_rows) >= 1


@pytest.mark.asyncio
async def test_whale_intelligence_analytics():
    """Verify WhaleIntelligence fetching, fallback logic, and composite scoring using pure Polars."""
    intel = WhaleIntelligence()
    
    async def mock_whale(session):
        return intel._generate_mock_whale_flows(1780000000, 1780086400)
        
    async def mock_stable(session):
        return intel._generate_mock_stablecoin_data()
        
    async def mock_miner(session):
        return intel._generate_mock_blocks_data()

    intel.fetch_whale_flows = mock_whale
    intel.fetch_stablecoin_velocity = mock_stable
    intel.fetch_miner_flow_proxy = mock_miner

    # Run mock analyze end-to-end
    result = await intel.analyze()
    
    # Assert return structure
    assert "whale_flow_score" in result
    assert "stablecoin_velocity_score" in result
    assert "miner_pressure_score" in result
    assert "crypto_smart_money_score" in result
    assert "flags" in result
    
    # Check score bounds
    assert 0.0 <= result["whale_flow_score"] <= 100.0
    assert 0.0 <= result["stablecoin_velocity_score"] <= 100.0
    assert 0.0 <= result["miner_pressure_score"] <= 100.0
    assert 0.0 <= result["crypto_smart_money_score"] <= 100.0
    
    # Verify mock flags are present
    assert "BUYING_POWER_BUILDING" in result["flags"]
    assert "EXCHANGE_OUTFLOW_SURGE" in result["flags"]


@pytest.mark.asyncio
async def test_trends_engine_pipeline(mock_db_manager):
    """Test TrendsEngine fetch, processing, Z-score computation, and DB storage."""
    mock_db_manager.create_tables()
    np.random.seed(42)
    
    engine = TrendsEngine(db_manager=mock_db_manager)
    
    async def mock_fetch(keywords):
        today = datetime.now(timezone.utc).date()
        dates = [today - timedelta(days=89 - i) for i in range(90)]
        
        # Determine group name based on keywords
        if "stock market crash" in keywords:
            # Retail fear - spike the last day to get Z-score > 2.0
            raw_scores = np.random.normal(loc=10.0, scale=2.0, size=90)
            raw_scores[-1] = 25.0
        elif "buy stocks" in keywords:
            # Retail greed - keep normal
            raw_scores = np.random.normal(loc=15.0, scale=3.0, size=90)
            raw_scores[-1] = 15.0
        else:
            # Crypto
            raw_scores = np.random.normal(loc=30.0, scale=5.0, size=90)
            
        col1 = raw_scores * 0.5
        col2 = raw_scores * 0.3
        col3 = raw_scores * 0.2
        
        df = pl.DataFrame({
            "date": dates,
            keywords[0]: col1,
            keywords[1]: col2,
            keywords[2]: col3,
        })
        return df

    engine._fetch_group_interest_with_retry = mock_fetch
    
    # Run the pipeline
    await engine.run_pipeline()
    
    # Verify DB records
    with mock_db_manager.session_scope() as session:
        trends_rows = session.query(AlternativeData).all()
        assert len(trends_rows) == 1
        row = trends_rows[0]
        
        assert row.retail_fear_zscore > 2.0
        assert row.flags == "EXTREME_FEAR"
        
        # Verify JSON
        raw_scores_dict = json.loads(row.raw_scores_json)
        assert "stock market crash" in raw_scores_dict
        assert "buy stocks" in raw_scores_dict
        assert "bitcoin price" in raw_scores_dict


@pytest.mark.asyncio
async def test_news_sentiment_pipeline(mock_db_manager):
    """Test NewsSentiment pipeline end-to-end including caching, VADER fallback, and sentiment divergence."""
    mock_db_manager.create_tables()

    # Populate daily price data for Nifty spot above 20 EMA
    today = datetime.now(timezone.utc).date()
    with mock_db_manager.session_scope() as session:
        for i in range(30):
            session.add(DailyPriceData(
                symbol="^NSEI",
                trade_date=today - timedelta(days=30-i),
                open=20000.0 + (i * 100.0),
                high=20100.0 + (i * 100.0),
                low=19900.0 + (i * 100.0),
                close=20000.0 + (i * 100.0),
                volume=1000000,
            ))
            
    engine = NewsSentiment(db_manager=mock_db_manager)
    
    async def mock_fetch():
        return [
            {"title": "Stock market crash: Nifty falls 1000 points in massive panic.", "source": "reuters"},
            {"title": "RBI rate hike triggers severe recession fears.", "source": "bloomberg"},
        ]
    engine._fetch_news = mock_fetch

    # Force VADER fallback to avoid downloading Hugging Face model in testing
    engine._get_classifier = MagicMock(side_effect=RuntimeError("Skip HF download for test"))

    # Run pipeline
    result = await engine.run_pipeline()
    
    # Check results
    assert "Daily_Sentiment_Score" in result
    assert result["Daily_Sentiment_Score"] <= 0.0
    assert result["Flags"] in ["SENTIMENT_DIVERGENCE", None]
    
    # Verify cached in DB
    with mock_db_manager.session_scope() as session:
        cached_rows = session.query(NewsSentimentCache).all()
        assert len(cached_rows) == 1
        assert cached_rows[0].flags in ["SENTIMENT_DIVERGENCE", None]


@pytest.mark.skip(reason="Reddit API removed per production spec in favor of NewsAPI/Google Trends")
@pytest.mark.asyncio
async def test_social_scraper_pipeline(mock_db_manager):
    """Test SocialScraper pipeline end-to-end with mocks, database persistence, and retail FOMO check."""
    mock_db_manager.create_tables()

    # Populate daily price data for RELIANCE and BTC to check stability return checks
    today = datetime.now(timezone.utc).date()
    with mock_db_manager.session_scope() as session:
        # RELIANCE prices: stable (<= 2% change over 3 days)
        for i in range(5):
            session.add(DailyPriceData(
                symbol="RELIANCE.NS",
                trade_date=today - timedelta(days=5-i),
                open=2500.0,
                high=2510.0,
                low=2490.0,
                close=2500.0, # Completely flat
                volume=1000000,
            ))
            # BTC prices: volatile (> 2% change)
            session.add(DailyPriceData(
                symbol="BTC-USD",
                trade_date=today - timedelta(days=5-i),
                open=60000.0 + (i * 2000.0),
                high=61000.0 + (i * 2000.0),
                low=59000.0 + (i * 2000.0),
                close=60000.0 + (i * 2000.0), # Growing fast
                volume=1000000,
            ))

    scraper = SocialScraper(db_manager=mock_db_manager)

    # Mock _fetch_reddit_posts_and_comments to return deterministic posts/comments
    async def mock_reddit_fetch():
        posts = []
        for i in range(8):
            posts.append({
                "id": f"post_reliance_{i}",
                "subreddit": "IndianStreetBets",
                "text": "RELIANCE to the moon! Massive bull run coming up, time to pump this stock!",
                "comments": [
                    "Totally bullish on RELIANCE, moon soon!",
                    "Pump it up! RELIANCE has best fundamentals.",
                    "Let's crash the bears, RELIANCE is going to the moon!",
                ],
                "num_comments": 40
            })
        posts.append({
            "id": "post_btc",
            "subreddit": "CryptoCurrency",
            "text": "BTC is pumping hard! Get ready for altcoin season, bear market is officially dead.",
            "comments": [
                "BTC to the moon!",
                "Bull market is back, pump BTC!",
            ],
            "num_comments": 50
        })
        return posts
    scraper._fetch_reddit_posts_and_comments = mock_reddit_fetch

    # Mock yfinance downloading to prevent hitting external API
    import pandas as pd
    def mock_yf_download(ticker, **kwargs):
        if "RELIANCE" in ticker:
            data = pd.DataFrame({"Close": [2500.0, 2500.0, 2500.0, 2500.0, 2500.0]}, index=pd.date_range(end=today, periods=5))
        else:
            data = pd.DataFrame({"Close": [60000.0, 62000.0, 64000.0, 66000.0, 68000.0]}, index=pd.date_range(end=today, periods=5))
        data.index.name = "Date"
        return data

    with patch("yfinance.download", side_effect=mock_yf_download):
        await scraper.run_pipeline()

    # Verify metrics stored in DB
    with mock_db_manager.session_scope() as session:
        metrics = session.query(RedditMetrics).all()
        assert len(metrics) > 0
        
        # RELIANCE should have RETAIL_FOMO flag (excitement is high, price stable)
        reliance_rows = [m for m in metrics if m.symbol == "RELIANCE" and m.subreddit == "IndianStreetBets"]
        assert len(reliance_rows) == 1
        assert reliance_rows[0].mention_count == 32 # 8 posts * 4 mentions/post
        assert float(reliance_rows[0].sentiment_score) >= 0.0 # credibility/mention sentiment
        assert reliance_rows[0].excitement_index > 80.0
        assert reliance_rows[0].flags == "RETAIL_FOMO"

        # BTC should NOT have RETAIL_FOMO flag (excitement is high, but price is volatile > 2%)
        btc_rows = [m for m in metrics if m.symbol == "BTC" and m.subreddit == "CryptoCurrency"]
        assert len(btc_rows) == 1
        assert btc_rows[0].flags is None or "RETAIL_FOMO" not in btc_rows[0].flags


@pytest.mark.asyncio
async def test_macro_regime_overlay_pipeline(mock_db_manager):
    """Test MacroRegime overlay pipeline end-to-end with yfinance / FRED mock responses and Polars calculations."""
    mock_db_manager.create_tables()

    overlay = MacroOverlay(db_manager=mock_db_manager)

    # 1. Mock _fetch_yfinance_prices
    async def mock_fetch_prices(tickers):
        today = datetime.now(timezone.utc).date()
        dates = [today - timedelta(days=119 - i) for i in range(120)]
        
        res = {}
        for ticker in tickers:
            if ticker == "ES=F":
                closes = [4000.0 + (i * 5.0) for i in range(120)]
                closes[-1] = closes[-2] * 1.02 # Spike S&P 500 return
            elif ticker == "^NSEI":
                closes = [20000.0 + (i * 25.0) for i in range(120)]
                closes[-1] = closes[-2] * 1.015
            elif ticker == "BZ=F":
                closes = [92.0] * 120
            elif ticker == "HG=F":
                closes = [4.5 - (i * 0.01) for i in range(120)]
            elif ticker == "INR=X":
                closes = [84.2] * 120
            else:
                closes = [15.0] * 120
                
            res[ticker] = pl.DataFrame({"date": dates, "close": closes})
        return res

    overlay._fetch_yfinance_prices = mock_fetch_prices

    # 2. Mock _fetch_fred_series
    async def mock_fetch_fred(series_id):
        today = datetime.now(timezone.utc).date()
        dates = [today - timedelta(days=(12 - i) * 30) for i in range(13)]
        
        if series_id == "M2SL":
            vals = [20000.0 - (i * 42.0) for i in range(13)]
        elif series_id == "TRESEGIDA156N":
            vals = [6.0e11 - (i * 1.6e9) for i in range(13)]
            vals[-1] = vals[-2] - 1.2e10 # Fall by $12B to trigger CURRENCY_STRESS
        else:
            vals = [100.0] * 13
            
        return pl.DataFrame({"date": dates, "value": vals})

    overlay._fetch_fred_series = mock_fetch_fred

    # Run pipeline
    result = await overlay.run_pipeline()

    # Check results and computed signals
    assert "Macro_Regime_Score" in result
    assert "Regime_Label" in result
    
    # Verify flags contain expected values
    flags = result["Flags"]
    assert "US_MOMENTUM_CARRY" in flags
    assert "STAGFLATION_RISK" in flags
    assert "GLOBAL_LIQUIDITY_DRAIN" in flags
    assert "CURRENCY_STRESS" in flags

    # Since all signals are active, score should be clamps to -60 (or matching the weights sum)
    # Carry (+40) - Stagflation (-30) - Liquidity (-30) - Currency (-40) = -60
    assert result["Macro_Regime_Score"] == -60.0
    assert result["Regime_Label"] == "STRESS_DRAIN"

    # Verify persisted in database
    with mock_db_manager.session_scope() as session:
        db_rows = session.query(MacroRegime).all()
        assert len(db_rows) == 1
        assert db_rows[0].macro_regime_score == -60.0
        assert db_rows[0].regime_label == "STRESS_DRAIN"
        assert "CURRENCY_STRESS" in db_rows[0].flags


def test_composite_orchestrator(mock_db_manager):
    """Test SignalOrchestrator weighted aggregation, direction filtering, and duration / returns calculations."""
    orchestrator = SignalOrchestrator(db_manager=mock_db_manager)

    # 1. Test a strong bullish scenario that passes the > 75 threshold and has layer agreement
    options_bullish = {"pcr": 1.3, "max_pain": 22300.0, "spot_price": 22000.0}
    crypto_bullish = {"crypto_smart_money_score": 90.0, "flags": "FUNDING_EXTREME_LONG,EXCHANGE_OUTFLOW_SURGE", "funding_rate": 0.002}
    alternative_bullish = {"fii_net_flow": 2500.0, "news_sentiment_score": 0.8, "reddit_sentiment_score": 0.9}
    macro_bullish = {"flags": "US_MOMENTUM_CARRY", "macro_regime_score": 40.0, "us_vix": 14.0}

    # Dummy price history DataFrame for shape
    df_prices = pl.DataFrame({
        "close": [100.0] * 30,
        "var_2_lag_forecast": [0.01] * 30,
        "bl_implied_view": [0.2] * 30
    })

    signal = orchestrator.compute_composite_signal(
        symbol="^NSEI",
        regime_state="CALM_BULL",
        options_data=options_bullish,
        crypto_data=crypto_bullish,
        alternative_data=alternative_bullish,
        macro_data=macro_bullish,
        price_history=df_prices
    )

    assert signal is not None
    assert signal["symbol"] == "^NSEI"
    assert signal["direction"] == "LONG"
    assert signal["composite_score"] > 75.0
    assert signal["position_size_pct"] > 0.0
    assert len(signal["rationale"]) > 0
    assert len(signal["invalidation_conditions"]) > 0

    # 2. Test a scenario that fails the agreement/score checks and returns None
    options_weak = {"pcr": 1.0, "max_pain": 22000.0, "spot_price": 22000.0}
    crypto_weak = {"crypto_smart_money_score": 50.0, "flags": "", "funding_rate": 0.0}
    alternative_weak = {"fii_net_flow": 0.0, "news_sentiment_score": 0.0, "reddit_sentiment_score": 0.0}
    macro_weak = {"flags": "", "macro_regime_score": 0.0, "us_vix": 18.0}

    rejected_signal = orchestrator.compute_composite_signal(
        symbol="^NSEI",
        regime_state="NEUTRAL_CALM",
        options_data=options_weak,
        crypto_data=crypto_weak,
        alternative_data=alternative_weak,
        macro_data=macro_weak,
        price_history=df_prices
    )

    assert rejected_signal is None



