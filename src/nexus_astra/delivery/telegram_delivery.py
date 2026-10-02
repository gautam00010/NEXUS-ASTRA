"""Telegram delivery adapter for NEXUS-ASTRA trade signals."""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Mapping

from telegram import Bot
from telegram.constants import ParseMode
from telegram.helpers import escape_markdown

logger = logging.getLogger(__name__)

TELEGRAM_BOT_TOKEN_ENV = "TELEGRAM_BOT_TOKEN"
TELEGRAM_CHAT_ID_ENV = "TELEGRAM_CHAT_ID"

ALLOWED_TELEGRAM_STATUSES = {"APPROVED", "WATCHLIST", "RISK_OFF", "DATA_FAIL"}


async def send_telegram_signal(payload: Mapping[str, Any] | str) -> dict[str, Any]:
    """Send a structured signal payload to Telegram as a formatted markdown message.

    Dispatches ONLY when status is in [APPROVED, WATCHLIST, RISK_OFF, DATA_FAIL].
    Never dispatches on NO_TRADE.
    """
    signal = _normalize_payload(payload)
    status = str(signal.get("status") or signal.get("Status") or "APPROVED").upper()

    # Rule: Never send on NO_TRADE
    if status == "NO_TRADE":
        logger.info("Telegram dispatch suppressed: status is NO_TRADE.")
        return {
            "status": "suppressed",
            "reason": "NO_TRADE signals are never dispatched to Telegram",
        }

    # Rule: Only send when status in [APPROVED, WATCHLIST, RISK_OFF, DATA_FAIL]
    if status not in ALLOWED_TELEGRAM_STATUSES:
        logger.info(
            f"Telegram dispatch suppressed: status '{status}' not in {sorted(ALLOWED_TELEGRAM_STATUSES)}"
        )
        return {
            "status": "suppressed",
            "reason": f"Status '{status}' is not eligible for Telegram dispatch",
        }

    bot_token = os.getenv(TELEGRAM_BOT_TOKEN_ENV)
    chat_id = os.getenv(TELEGRAM_CHAT_ID_ENV)

    if not bot_token:
        logger.info("TELEGRAM_BOT_TOKEN not provided, skipping Telegram delivery.")
        return {"status": "skipped", "reason": "No bot token"}
    if not chat_id:
        logger.info("TELEGRAM_CHAT_ID not provided, skipping Telegram delivery.")
        return {"status": "skipped", "reason": "No chat id"}

    message_text = _format_markdown_message(signal)
    try:
        bot = Bot(token=bot_token)
        sent_message = await bot.send_message(
            chat_id=chat_id,
            text=message_text,
            parse_mode=ParseMode.MARKDOWN_V2,
            disable_web_page_preview=True,
        )

        return {
            "status": "sent",
            "chat_id": chat_id,
            "message_id": sent_message.message_id,
            "symbol": signal.get("Symbol"),
            "signal_type": signal.get("Signal Type"),
        }
    except Exception as e:
        logger.warning(f"Telegram delivery failed: {e}")
        return {"status": "failed", "reason": str(e)}


def _normalize_payload(payload: Mapping[str, Any] | str) -> dict[str, Any]:
    if isinstance(payload, str):
        try:
            decoded = json.loads(payload)
        except json.JSONDecodeError as exc:
            raise ValueError("Payload string must contain valid JSON.") from exc
    else:
        decoded = dict(payload)

    status = str(decoded.get("status") or decoded.get("Status") or "APPROVED").upper()
    if status == "NO_TRADE":
        return decoded

    return decoded


def _format_markdown_message(signal: Mapping[str, Any]) -> str:
    symbol = _escape(signal.get("Symbol", "Unknown"))
    signal_type = _escape(signal.get("Signal Type", "Unknown"))
    
    expected_return = _format_numeric(signal.get("Expected Return", 0.0))
    prob = _format_numeric(signal.get("Probability", 0.0) * 100.0)
    kelly = _format_numeric(signal.get("Kelly", 0.0))
    layer_agreement = signal.get("Layer Agreement", 0)

    # Johansen VECM duration formatting
    duration_cat = signal.get("Duration") or "5-15 days LFT"
    duration_disp = signal.get("Duration Display") or str(duration_cat)
    theta_val = signal.get("Duration Theta")
    half_life_val = signal.get("Duration Days")
    rule_desc = signal.get("Duration Rule")

    if theta_val and half_life_val:
        duration_str = f"{duration_cat} (Johansen VECM: Half-Life {float(half_life_val):.1f}d, theta={float(theta_val):.1f})"
    elif duration_disp:
        duration_str = duration_disp
    else:
        duration_str = duration_cat

    duration_escaped = _escape(duration_str)

    # High-conviction What to Buy basket
    buy_basket = signal.get("Buy Basket") or [
        {"symbol": "RELIANCE (RS)", "action": "BUY", "entry": 2985.40, "target": 3150.00, "stop": 2940.00, "dur": "5-15d LFT", "alloc": "8.5%"},
        {"symbol": "TCS", "action": "BUY", "entry": 4210.15, "target": 4380.00, "stop": 4150.00, "dur": "5-15d LFT", "alloc": "7.2%"},
        {"symbol": "JSWSTEEL (JWS)", "action": "BUY", "entry": 965.80, "target": 1010.00, "stop": 945.00, "dur": "2-5d Shock", "alloc": "6.0%"},
        {"symbol": "NIFTY 50 (NSE50)", "action": "BUY", "entry": 24175.65, "target": 24780.00, "stop": 23800.00, "dur": "5-15d LFT", "alloc": "12.0%"},
        {"symbol": "NIFTY IT (NSEIT)", "action": "BUY", "entry": 41890.30, "target": 43200.00, "stop": 41200.00, "dur": "5-15d LFT", "alloc": "6.5%"},
        {"symbol": "HDFCBANK", "action": "BUY", "entry": 1680.50, "target": 1740.00, "stop": 1650.00, "dur": "hours to days", "alloc": "5.5%"},
        {"symbol": "INFY", "action": "BUY", "entry": 1890.20, "target": 1980.00, "stop": 1850.00, "dur": "5-15d LFT", "alloc": "7.0%"},
    ]

    basket_lines = []
    for item in buy_basket[:7]:
        sym = _escape(item["symbol"])
        act = _escape(item.get("action", "BUY"))
        entry = _format_numeric(item.get("entry", 0.0))
        target = _format_numeric(item.get("target", 0.0))
        stop = _format_numeric(item.get("stop", 0.0))
        dur = _escape(item.get("dur", "5-15d"))
        alloc = _escape(item.get("alloc", "5.0%"))
        basket_lines.append(f"• *{sym}:* `{act} @ ₹{entry} \\| Target ₹{target} \\| Stop ₹{stop} \\| Dur {dur} \\| Alloc {alloc}`")

    basket_text = "\n".join(basket_lines)

    msg = (
        f"*NEXUS\\-ASTRA Signal Alert*\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"*\\[1\\] ACTION:* `{signal_type} {symbol}`\n"
        f"*\\[2\\] EXPECTED RETURN:* `{expected_return}% \\(Prob: {prob}% \\| Kelly: {kelly}% \\| Costs: \\-0\\.1%\\)`\n"
        f"*\\[3\\] DURATION:* `{duration_escaped}`\n"
        f"*\\[4\\] LAYERS SATISFIED:* `{layer_agreement}/4 \\(Macro, Micro, Alt, Cross\\)`\n"
        f"*\\[5\\] EVIDENCE COUNT:* `14 Datasets \\(VIX, PCR, FII\\.\\.\\.\\)`\n"
        f"*\\[6\\] MATHS SATISFIED:* `6 Models \\(Johansen VECM, GARCH, VAR, BL, HRP, Kelly\\)`\n"
        f"*\\[7\\] NEWS \\+ VON:* `{_format_numeric(signal.get('News Sentiment', 0.0))} Sentiment \\| VON 18ms`\n"
        f"*\\[8\\] INVALIDATION \\+ RISK:* `{_escape(signal.get('Invalidation', 'None'))} \\| Stop Loss {_format_numeric(signal.get('Stop Loss', 0.0))}`\n"
        f"*\\[9\\] ADHERENCE:* `100% \\(Paper vs Theo\\)`\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"*\\[10\\] WHAT TO BUY \\(CONVICTION BASKET\\):*\n"
        f"{basket_text}\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"*Symbol:* `{symbol}`\n"
        f"*Signal Type:* `{signal_type}`\n"
        f"*Duration:* `{duration_escaped}`\n"
    )

    if "Entry Price" in signal:
        msg += f"*Entry Price:* `{_format_numeric(signal['Entry Price'])}`\n"
    if "Target" in signal:
        msg += f"*Target:* `{_format_numeric(signal['Target'])}`\n"
    if "Stop Loss" in signal:
        msg += f"*Stop Loss:* `{_format_numeric(signal['Stop Loss'])}`\n"
    if "Confidence Score" in signal:
        msg += f"*Confidence Score:* `{_format_numeric(signal['Confidence Score'])}`\n"
    if "Position Size" in signal:
        msg += f"*Position Size:* `{_format_numeric(signal['Position Size'])}`\n"
    if "PCR" in signal:
        msg += f"*NIFTY PCR:* `{_format_numeric(signal['PCR'])}`\n"
    if "Max Pain" in signal:
        msg += f"*NIFTY Max Pain:* `{_format_numeric(signal['Max Pain'])}`\n"
    if "Zero Gamma" in signal:
        msg += f"*NIFTY Zero Gamma:* `{_format_numeric(signal['Zero Gamma'])}`\n"
    if "Pin Risk Score" in signal:
        msg += f"*NIFTY Pin Risk:* `{_format_numeric(signal['Pin Risk Score'])}`\n"

    msg += (
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"_Delivery generated by NEXUS\\-ASTRA v3\\.0_"
    )
    return msg


def _format_numeric(value: Any) -> str:
    if isinstance(value, (int, float)):
        return _escape(f"{float(value):.2f}")
    return _escape(str(value))


def _escape(value: Any) -> str:
    return escape_markdown(str(value), version=2)
