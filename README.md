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
