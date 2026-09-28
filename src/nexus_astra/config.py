"""Single source of truth for secrets and configuration."""
from __future__ import annotations
import logging
import os

logger = logging.getLogger(__name__)

try:
    import streamlit as st
except ImportError:
    st = None


class Settings:
    """Centralised secrets resolver. Returns None (never raises) when key missing."""

    # Keys that are *required* for core functionality
    REQUIRED_KEYS = {"FRED_API_KEY", "NEWS_API_KEY"}
    # Optional – missing is a SKIP, not an error
    OPTIONAL_KEYS = {"FINNHUB_API_KEY", "ZERODHA_API_KEY", "ZERODHA_SECRET",
                     "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID",
                     "SMTP_USER", "SMTP_PASS", "SMTP_HOST", "ALERT_EMAIL"}

    @staticmethod
    def get_secret(key: str) -> str | None:
        """Resolve secret from env -> Streamlit secrets -> None."""
        # 1. OS environment variable (works in CLI, CI, Docker)
        val = os.getenv(key)
        if val:
            return val

        # 2. Streamlit secrets (works on Cloud / local .streamlit/secrets.toml)
        if st is not None:
            try:
                if hasattr(st, "secrets") and key in st.secrets:
                    return st.secrets[key]
            except Exception:
                pass

        # 3. Missing
        if key in Settings.REQUIRED_KEYS:
            logger.warning(f"CONFIG: Required key {key!r} missing – pipeline may degrade")
        else:
            logger.info(f"CONFIG: Optional key {key!r} missing – SKIP sleeve")
        return None


config = Settings()
