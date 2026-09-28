# NEXUS-ASTRA v3.0 Handoff Summary

This file summarizes the current implementation state of the project.

## Project Layout

- `src/nexus_astra/data_ingestion/`
- `src/nexus_astra/feature_engineering/`
- `src/nexus_astra/ml_models/`
- `src/nexus_astra/risk_management/`
- `src/nexus_astra/delivery/`
- `tests/`

## Implemented Modules

### Data Ingestion

- `src/nexus_astra/data_ingestion/database.py`
  - SQLite bootstrap for `astra_market_data.db`
  - SQLAlchemy declarative models:
    - `DailyPriceData`
    - `InstitutionalFlows`
    - `MacroRegime`
  - Singleton session manager: `DatabaseManager`

- `src/nexus_astra/data_ingestion/data_fetcher.py`
  - Async `MarketDataFetcher`
  - Downloads 5 years of daily data using `yfinance`
  - Loads daily market data and macro data into SQLite

- `src/nexus_astra/data_ingestion/options_fetcher.py`
  - `NSEOptionsFetcher`
  - NSE option-chain fetcher using `requests`
  - Nearest monthly expiry selection
  - Summary output with:
    - `date`
    - `underlying`
    - `pcr_oi`
    - `max_pain_strike`
    - `spot_distance_pct`
    - `unusual_activity_flag`

### Feature Engineering

- `src/nexus_astra/feature_engineering/alpha_features.py`
  - `AlphaFeatures`
  - Bid-ask/volume imbalance proxy
  - 20D and 60D historical volatility
  - Vol-of-vol
  - 50D and 200D EMA distance
  - 14D RSI

- `src/nexus_astra/feature_engineering/regime_detector.py`
  - `detect_market_regime(...)`
  - Detects:
    - `FII_EXHAUSTION_SETUP`
    - `BEAR_MOMENTUM`
    - `CALM_BULL`

- `src/nexus_astra/feature_engineering/gamma_features.py`
  - `GammaExposure`
  - Gamma exposure per strike
  - Zero gamma level
  - Pin risk score

### Models

- `src/nexus_astra/ml_models/ensemble_engine.py`
  - `EnsembleEngine`
  - XGBoost base model
  - Walk-forward validation:
    - 252-day train window
    - 63-day test window
  - LogisticRegression meta-learner
  - Composite signal score from 0 to 100
  - Strict filter for composite score > 75

### Risk Management

- `src/nexus_astra/risk_management/risk_manager.py`
  - Fractional Kelly sizing with strict `0.25x` multiplier
  - Volatility targeting when VIX > 25
  - Final capital allocation percentage helper

### Delivery

- `src/nexus_astra/delivery/telegram_delivery.py`
  - Async Telegram sender using `python-telegram-bot`
  - Reads credentials from:
    - `TELEGRAM_BOT_TOKEN`
    - `TELEGRAM_CHAT_ID`
  - Formats trade alerts in professional MarkdownV2

### Pipeline Entry Point

- `main.py`
  - Orchestrates the full pipeline sequentially:
    1. Fetch data
    2. Engineer features
    3. Detect regime
    4. Score signals with ML ensemble
    5. Size via risk manager
    6. Send final output via Telegram

### Workflow

- `.github/workflows/astra_daily_run.yml`
  - Scheduled run at 11:30 PM IST on weekdays
  - Installs `requirements.txt`
  - Runs `python main.py`
  - Uses GitHub Secrets for Telegram credentials

## Key Environment Variables

- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`

## Notes

- Core files were syntax-validated in the editor environment.
- Some live integrations were not executed here, including NSE API requests and Telegram delivery.
