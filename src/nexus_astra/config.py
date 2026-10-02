"""Single source of truth for secrets and configuration."""
from __future__ import annotations
import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

# Automatically load .env file from project root
try:
    from dotenv import load_dotenv
    _repo_root = Path(__file__).resolve().parents[2]
    _env_file = _repo_root / ".env"
    if _env_file.exists():
        load_dotenv(_env_file)
    else:
        load_dotenv()
except Exception:
    # Fallback basic parser if python-dotenv isn't loaded
    try:
        _repo_root = Path(__file__).resolve().parents[2]
        _env_file = _repo_root / ".env"
        if _env_file.exists():
            with open(_env_file, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        k, v = line.split("=", 1)
                        k, v = k.strip(), v.strip().strip("'\"")
                        if k and k not in os.environ:
                            os.environ[k] = v
    except Exception:
        pass

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
        if val and val != "xxx" and not val.startswith("your_"):
            return val

        # 2. Streamlit secrets (works on Cloud / local .streamlit/secrets.toml)
        if st is not None:
            try:
                if hasattr(st, "secrets") and key in st.secrets:
                    s_val = st.secrets[key]
                    if s_val and s_val != "xxx" and not str(s_val).startswith("your_"):
                        return str(s_val)
            except Exception:
                pass

        # 3. Missing
        if key in Settings.REQUIRED_KEYS:
            logger.warning(f"CONFIG: Required key {key!r} missing – pipeline may degrade")
        else:
            logger.info(f"CONFIG: Optional key {key!r} missing – SKIP sleeve")
        return None


config = Settings()
