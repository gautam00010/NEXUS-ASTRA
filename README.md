# NEXUS-ASTRA

Institutional Quantitative Intelligence Platform

## Production Setup (5 mins manual)

1. **Telegram Alerts:**
   - Create a Telegram bot via `@BotFather`
   - Retrieve the `token` and `chat_id`

2. **API Keys:**
   - FRED (for DXY/US10Y): Get a free key at `fred.stlouisfed.org`
   - NewsAPI: Get a free key at `newsapi.org`
   - Reddit: Create an app for client ID and secret
   - Fyers/Upstox: Free API for NSE live data

3. **Streamlit Cloud Deployment:**
   - Connect your GitHub repo (NEXUS-ASTRA) to Streamlit Cloud
   - Add your secrets in the Streamlit Cloud dashboard: `App > Settings > Secrets`. You can copy the format from `.streamlit/secrets.toml.example`
   - Ensure the Python version is set to 3.12
   - Main file path: `app.py`

4. **Local / OCI Deployment:**
   - Run `docker-compose up` with your `.env` configured.
## Dynamic regime-adaptive weights

NEXUS-ASTRA calibrates dataset influence from HMM/ADX/GARCH/VIX/PCR context rather than fixed percentages.

The formula is:

`weight_i(t) = base_weight_i * regime_multiplier_i(t) * max(0.2, recent_sharpe_i) / realized_vol_i`

Weights are then normalized to sum to 1.0. Recency uses exponential decay `0.94`; negative-Sharpe datasets keep a 5% floor and can recover. Soft states are `HOLD < 0.50`, `WATCH 0.50-0.65`, `TRADE 0.65-0.80`, and `STRONG_TRADE > 0.80`. A HOLD still produces the daily Telegram digest.
