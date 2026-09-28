"""Polars-native NSE option-chain fetcher and summarizer."""

from __future__ import annotations

import calendar
import random
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any

import polars as pl
import requests


NSE_HOME_URL = "https://www.nseindia.com"
NSE_OPTION_CHAIN_URL = "https://www.nseindia.com/api/option-chain-indices"

UNDERLYING_TO_SYMBOL = {
    "NIFTY": "NIFTY",
    "BANKNIFTY": "BANKNIFTY",
}


@dataclass(frozen=True)
class OptionChainMetrics:
    """Structured summary for a single underlying and expiry."""

    date: date
    underlying: str
    pcr_oi: float
    max_pain_strike: float
    spot_distance_pct: float
    unusual_activity_flag: str


class NSEOptionsFetcher:
    """Fetch NSE index option chains and derive a compact options regime summary."""

    def __init__(
        self,
        *,
        session: requests.Session | None = None,
        max_retries: int = 5,
        base_backoff_seconds: float = 0.75,
    ) -> None:
        self.session = session or self._build_session()
        self.max_retries = max_retries
        self.base_backoff_seconds = base_backoff_seconds

    def fetch_option_chain_summary(self, underlying: str) -> pl.DataFrame:
        """Return a one-row Polars dataframe with option-chain regime metrics."""

        symbol = self._normalize_underlying(underlying)
        payload = self._fetch_option_chain_payload(symbol)
        summary_frame = self._summarize_payload(payload, symbol)
        return summary_frame.select(
            ["date", "underlying", "pcr_oi", "max_pain_strike", "spot_distance_pct", "unusual_activity_flag"]
        )

    def fetch_full_option_chain(self, underlying: str) -> pl.DataFrame:
        """Return the full option chain for the nearest monthly expiry as a Polars dataframe."""

        symbol = self._normalize_underlying(underlying)
        payload = self._fetch_option_chain_payload(symbol)
        expiry = self._select_nearest_monthly_expiry(payload)
        return self._build_option_chain_frame(payload, expiry)

    def _build_session(self) -> requests.Session:
        session = requests.Session()
        session.headers.update(
            {
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
                ),
                "Accept": "application/json, text/plain, */*",
                "Accept-Language": "en-US,en;q=0.9",
                "Connection": "keep-alive",
                "Referer": "https://www.nseindia.com/option-chain",
            }
        )
        self._prime_cookies(session)
        return session

    def _prime_cookies(self, session: requests.Session) -> None:
        try:
            session.get(NSE_HOME_URL, timeout=10)
            session.get("https://www.nseindia.com/option-chain", timeout=10)
        except requests.RequestException:
            # NSE sometimes blocks the bootstrap call; the retry path will re-attempt.
            return

    def _normalize_underlying(self, underlying: str) -> str:
        normalized = underlying.strip().upper()
        if normalized not in UNDERLYING_TO_SYMBOL:
            raise ValueError("underlying must be one of: NIFTY, BANKNIFTY")
        return UNDERLYING_TO_SYMBOL[normalized]

    def _fetch_option_chain_payload(self, symbol: str) -> dict[str, Any]:
        params = {"symbol": symbol}
        last_error: Exception | None = None

        for attempt in range(self.max_retries):
            try:
                response = self.session.get(NSE_OPTION_CHAIN_URL, params=params, timeout=20)
                if response.status_code in {401, 403, 429}:
                    self._prime_cookies(self.session)
                    raise requests.HTTPError(f"NSE returned HTTP {response.status_code}")

                response.raise_for_status()
                payload = response.json()
                if not isinstance(payload, dict) or "records" not in payload:
                    raise ValueError("Unexpected NSE response payload.")
                return payload
            except (requests.RequestException, ValueError) as exc:
                last_error = exc
                if attempt == self.max_retries - 1:
                    break

                sleep_seconds = self.base_backoff_seconds * (2**attempt)
                jitter = random.uniform(0.0, self.base_backoff_seconds)
                self._prime_cookies(self.session)
                self._sleep(sleep_seconds + jitter)

        raise RuntimeError("Failed to fetch NSE option chain after retries.") from last_error

    def _summarize_payload(self, payload: dict[str, Any], symbol: str) -> pl.DataFrame:
        full_chain = self._build_option_chain_frame(payload, self._select_nearest_monthly_expiry(payload))
        if full_chain.is_empty():
            return pl.DataFrame(
                [
                    {
                        "date": datetime.now(timezone.utc).date(),
                        "underlying": symbol,
                        "pcr_oi": None,
                        "max_pain_strike": None,
                        "spot_distance_pct": None,
                        "unusual_activity_flag": "NORMAL",
                    }
                ]
            )

        spot = self._extract_spot_value(payload)
        total_call_oi = float(full_chain.get_column("call_oi").sum())
        total_put_oi = float(full_chain.get_column("put_oi").sum())
        pcr_oi = float("inf") if total_call_oi == 0.0 else total_put_oi / total_call_oi
        max_pain_strike = self._calculate_max_pain(full_chain)
        spot_distance_pct = 0.0 if spot == 0.0 else ((spot - max_pain_strike) / spot) * 100.0
        unusual_activity_flag = self._classify_unusual_activity(full_chain, pcr_oi)

        metrics = OptionChainMetrics(
            date=datetime.now(timezone.utc).date(),
            underlying=symbol,
            pcr_oi=pcr_oi,
            max_pain_strike=max_pain_strike,
            spot_distance_pct=spot_distance_pct,
            unusual_activity_flag=unusual_activity_flag,
        )
        return pl.DataFrame([metrics.__dict__])

    def _build_option_chain_frame(self, payload: dict[str, Any], expiry: date) -> pl.DataFrame:
        records = payload.get("records", {}).get("data", [])
        if not records:
            return pl.DataFrame()

        rows: list[dict[str, Any]] = []
        expiry_label = expiry.strftime("%d-%b-%Y").upper()

        for record in records:
            if record.get("expiryDate", "").upper() != expiry_label:
                continue

            strike = record.get("strikePrice")
            call_data = record.get("CE", {}) or {}
            put_data = record.get("PE", {}) or {}

            rows.append(
                {
                    "expiry_date": expiry,
                    "strike": float(strike) if strike is not None else None,
                    "call_oi": float(call_data.get("openInterest") or 0.0),
                    "put_oi": float(put_data.get("openInterest") or 0.0),
                    "call_change_oi": float(call_data.get("changeinOpenInterest") or 0.0),
                    "put_change_oi": float(put_data.get("changeinOpenInterest") or 0.0),
                    "call_volume": float(call_data.get("totalTradedVolume") or 0.0),
                    "put_volume": float(put_data.get("totalTradedVolume") or 0.0),
                    "call_ltp": float(call_data.get("lastPrice") or 0.0),
                    "put_ltp": float(put_data.get("lastPrice") or 0.0),
                    "underlying_value": float(payload.get("records", {}).get("underlyingValue") or 0.0),
                }
            )

        if not rows:
            return pl.DataFrame()

        return (
            pl.DataFrame(rows)
            .with_columns(
                pl.col("expiry_date").cast(pl.Date),
                pl.col("strike").cast(pl.Float64),
                pl.col("call_oi").cast(pl.Float64),
                pl.col("put_oi").cast(pl.Float64),
                pl.col("call_change_oi").cast(pl.Float64),
                pl.col("put_change_oi").cast(pl.Float64),
                pl.col("call_volume").cast(pl.Float64),
                pl.col("put_volume").cast(pl.Float64),
                pl.col("call_ltp").cast(pl.Float64),
                pl.col("put_ltp").cast(pl.Float64),
                pl.col("underlying_value").cast(pl.Float64),
            )
            .sort("strike")
        )

    def _select_nearest_monthly_expiry(self, payload: dict[str, Any]) -> date:
        expiry_dates = payload.get("records", {}).get("expiryDates", [])
        parsed_dates = [self._parse_expiry_date(expiry) for expiry in expiry_dates]
        future_dates = sorted(expiry for expiry in parsed_dates if expiry >= datetime.now(timezone.utc).date())

        if not future_dates:
            raise ValueError("No future expiries were returned by the NSE API.")

        first_month = (future_dates[0].year, future_dates[0].month)
        nearest_month_dates = [expiry for expiry in future_dates if (expiry.year, expiry.month) == first_month]
        return max(nearest_month_dates)

    def _calculate_max_pain(self, chain: pl.DataFrame) -> float:
        sub_df = chain.select(["strike", "call_oi", "put_oi"]).drop_nulls()
        if sub_df.is_empty():
            return 0.0

        candidates = sub_df.select(pl.col("strike").cast(pl.Float64).alias("candidate_strike")).unique()
        options = sub_df.select([
            pl.col("strike").cast(pl.Float64).alias("option_strike"),
            pl.col("call_oi").cast(pl.Float64),
            pl.col("put_oi").cast(pl.Float64)
        ])

        pain_surface = (
            candidates.join(options, how="cross")
            .with_columns(
                pl.when(pl.col("option_strike") > pl.col("candidate_strike"))
                .then(pl.col("call_oi") * (pl.col("option_strike") - pl.col("candidate_strike")))
                .otherwise(0.0)
                .alias("call_pain"),
                pl.when(pl.col("candidate_strike") > pl.col("option_strike"))
                .then(pl.col("put_oi") * (pl.col("candidate_strike") - pl.col("option_strike")))
                .otherwise(0.0)
                .alias("put_pain"),
            )
            .with_columns((pl.col("call_pain") + pl.col("put_pain")).alias("total_pain"))
        )

        result = (
            pain_surface.group_by("candidate_strike")
            .agg(pl.col("total_pain").sum().alias("total_pain"))
            .sort(["total_pain", "candidate_strike"])
            .limit(1)
        )

        if result.is_empty():
            return 0.0

        return float(result.get_column("candidate_strike")[0])

    def _classify_unusual_activity(self, chain: pl.DataFrame, pcr_oi: float) -> str:
        strike_oi = chain.with_columns((pl.col("call_oi") + pl.col("put_oi")).alias("total_oi_at_strike"))
        mean_oi = float(strike_oi.get_column("total_oi_at_strike").mean() or 0.0)
        max_oi = float(strike_oi.get_column("total_oi_at_strike").max() or 0.0)
        concentration_ratio = float("inf") if mean_oi == 0.0 else max_oi / mean_oi

        if concentration_ratio > 2.0:
            return "INSTITUTIONAL_POSITIONING"
        if pcr_oi > 1.3:
            return "EXTREME_BEARISH"
        if pcr_oi < 0.8:
            return "EXTREME_BULLISH"
        return "NORMAL"

    def _extract_spot_value(self, payload: dict[str, Any]) -> float:
        spot_value = payload.get("records", {}).get("underlyingValue")
        return float(spot_value or 0.0)

    @staticmethod
    def _parse_expiry_date(expiry: str) -> date:
        return datetime.strptime(expiry.strip(), "%d-%b-%Y").date()

    @staticmethod
    def _sleep(seconds: float) -> None:
        import time

        time.sleep(max(0.0, seconds))


def fetch_option_chain_summary(underlying: str) -> pl.DataFrame:
    """Convenience wrapper that returns the nearest monthly expiry summary."""

    return NSEOptionsFetcher().fetch_option_chain_summary(underlying)


def fetch_full_option_chain(underlying: str) -> pl.DataFrame:
    """Convenience wrapper that returns the full option-chain dataframe."""

    return NSEOptionsFetcher().fetch_full_option_chain(underlying)
