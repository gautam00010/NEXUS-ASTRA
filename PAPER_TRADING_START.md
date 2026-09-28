# 🚀 NEXUS-ASTRA // PAPER TRADING LAUNCH RUNBOOK
**Target Go-Live Date:** Tomorrow Morning (08:00 AM IST / 09:15 AM Market Open)  
**System Mode:** SIGNAL-ONLY // DUAL-LEDGER PAPER TRADING // 18ms VON ROUTER

---

## ⚡ 1. TONIGHT'S VERIFICATION (Pre-Flight Checks)

### Step 1.1: Local Pipeline Run
Run the end-to-end quant brain once to verify database seeding and signal generation:
```bash
python main.py
```
- **Expected Outcome:** Exits cleanly with status code `0`.
- **Database Verification:** Check that `astra_market_data.db` has populated tables:
  ```bash
  sqlite3 astra_market_data.db "SELECT count(*) FROM prices_raw; SELECT count(*) FROM theoretical_trades;"
  ```
  *(Should return >3,500 prices and >0 theoretical trades).*

### Step 1.2: Launch Bloomberg Mobile Terminal
Launch the Streamlit Bloomberg UI:
```bash
streamlit run app.py
```
- Open in your browser (or mobile simulator at 390px width):
  - **URL:** `http://localhost:8501`
  - **[TAPE] Feed:** Verify live NSE symbols (`RELIANCE`, `HDFCBANK`, `INFY`, `^NSEI`) appear with US influence tags `[SPX-1.2% VIX+10%]` and math tags `[Johansen+GARCH+Kelly]`.
  - **[LEDGER] Dual Ledger:** Verify Theoretical Trades (Immutable) are listed. Test recording a sample fill in the **RECORD FILL** form to verify that slippage (`actual - theoretical`) is calculated and saved.
  - **[EVIDENCE] Dossier:** Review Point-in-Time datasets (peoples, companies, evidence, market, economics, and Devil's Advocate counter-thesis).
  - **[PERF] & [RISK]:** Check Sharpe, Sortino, adherence curves, and risk caps (15% position limit, 30% sector limit, 20% fractional Kelly).

---

## ⏰ 2. TOMORROW MORNING SCHEDULE (Daily Workflow)

### 08:00 AM IST — Automated GitHub Actions Run
- The GitHub Action workflow (`.github/workflows/astra_daily_run.yml`) triggers automatically at `02:30 UTC` (08:00 AM IST, Mon-Fri).
- **Pipeline Execution:**
  - Ingests latest overnight US market data (SPX, VIX, US10Y, DXY via Finnhub & FRED).
  - Evaluates the **US Influence Gate** (applies 50% position reduction or `RISK_OFF` if SPX < -1.5% and VIX spikes).
  - Refreshes NSE/BSE and crypto prices.
  - Executes VON System One multi-layer sentiment and alpha features.
  - Computes composite signal and generates trade thesis.
- **Alert Dispatch:**
  - If a signal clears conviction (`APPROVED`, `WATCH`, `RISK_OFF`, or `DATA_FAIL`), a formatted alert is sent to your **Telegram**.
  - On `NO_TRADE` (no setup clears conviction), it runs quietly without spamming.
  - Execution logs are automatically uploaded as GitHub Action artifacts (`astra-daily-logs`).

### 09:15 AM IST — Market Open & Manual Execution
1. Check your Telegram notification and open the Bloomberg Mobile Terminal (`app.py`).
2. If an **`APPROVED`** signal is present:
   - Check the **[EVIDENCE]** tab for the thesis, invalidation levels, and Devil's Advocate counter-risk.
   - Manually place the paper trade or market order in your brokerage account (e.g. Zerodha Kite).
3. **Record Actual Fill in Dual Ledger:**
   - Switch to the **[LEDGER]** tab in `app.py`.
   - Select the `THEORETICAL ID`.
   - Enter your `ACTUAL FILL PRICE` and fill time.
   - Tap **RECORD FILL INTO DUAL LEDGER** (44px tap target).
   - The system immediately commits the fill to `ActualFills`, computes real slippage (`actual_price - theoretical_entry`), and updates tracking error.

---

## 🛡️ 3. CONTINUOUS RISK & ADHERENCE MONITORING

### Daily: Dual Ledger Tracking & Kill Switch
- The paper trader logs daily performance to `AdherenceDaily`:
  - **Theoretical P&L:** P&L assuming exact signal entry and mathematical cost model.
  - **Actual P&L:** P&L based on your recorded execution fills.
  - **Tracking Error & Slippage:** Tracks deviation between model and execution.
- **Automated Circuit Breaker:**
  - If Drawdown exceeds **15.0%** -> Hard `KILL_SWITCH` engaged, locks new signals.
  - If Adherence drops below **50.0%** -> Model alerts execution drift.
  - If 20-fill Slippage exceeds **50 bps** -> Flagged as excessive slippage.

### Weekly: Routine Review
- **Every Friday Post-Close:**
  1. Review the **[PERF]** tab: check realized Sharpe ratio after costs, average slippage drag, and win rate.
  2. Run walkforward backtesting on new historical data:
     ```bash
     python src/nexus_astra/backtesting/walkforward_engine.py RELIANCE
     ```
  3. Review the **[EVIDENCE]** Devil's Advocate invalidations to identify any structural regime changes.

---

## 🔑 4. SECRETS & KEYS CONFIGURATION

Verify your keys in `.env` (for local runs) and GitHub Secrets / Streamlit Cloud Secrets:

| Secret Name | Purpose | Status |
|---|---|---|
| `FRED_API_KEY` | US Macro (DXY, US10Y, Crude, Gold) | ✅ Available |
| `NEWS_API_KEY` | Global & India Market Headlines | ✅ Available |
| `FINNHUB_API_KEY` | US Equities (^GSPC, ^IXIC, ^VIX) & Company News | ✅ Available |
| `TELEGRAM_BOT_TOKEN` | Automated Signal Alerts | ⏳ Optional (Add anytime) |
| `TELEGRAM_CHAT_ID` | Telegram Alert Target Channel/User | ⏳ Optional (Add anytime) |

*If any optional key is missing, the system gracefully logs `SKIP` and falls back to free tiers without crashing.*

---

## 🌐 5. STREAMLIT CLOUD DEPLOYMENT GUIDE

1. **Push Repository to GitHub:**
   ```bash
   git add .
   git commit -m "Finalize production Bloomberg mobile terminal, live bootstrapper, and dual ledger"
   git push origin main
   ```
2. **Connect to Streamlit Cloud:**
   - Go to [share.streamlit.io](https://share.streamlit.io).
   - Select repository: `<your-username>/NEXUS-ASTRA`.
   - Main file path: `app.py`.
   - Python version: `3.12`.
3. **Configure Secrets in Streamlit Cloud Settings:**
   - Under App Settings -> **Secrets**, paste your keys:
     ```toml
     FRED_API_KEY = "your_fred_key"
     NEWS_API_KEY = "your_news_key"
     FINNHUB_API_KEY = "your_finnhub_key"
     TELEGRAM_BOT_TOKEN = "your_bot_token"
     TELEGRAM_CHAT_ID = "your_chat_id"
     ```
4. **Test on Mobile:**
   - Open the live app link on your phone (Safari/Chrome at 390px width).
   - Add to Home Screen for a dedicated Bloomberg terminal experience!
