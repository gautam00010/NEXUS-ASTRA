"""Regime detection logic for NEXUS-ASTRA market structure signals."""

from __future__ import annotations

from typing import Any

import polars as pl


def detect_market_regime(
    institutional_flows: pl.DataFrame,
    macro_regime: pl.DataFrame,
) -> dict[str, Any]:
    """Detect the current market regime using institutional flows and macro inputs.

    The FII exhaustion setup is flagged when the last three days satisfy all of the
    following conditions:
    - FII net selling is above 5,000 Cr on each day
    - Selling magnitude strictly decelerates across the 3-day window
      (day 3 < day 2 < day 1)
    - India VIX is above 20 on the latest day
    """

    flows = _standardize_columns(
        institutional_flows,
        {
            "Date": "date",
            "FII_Buy": "fii_buy",
            "FII_Sell": "fii_sell",
            "DII_Buy": "dii_buy",
            "DII_Sell": "dii_sell",
            "Net_FII": "net_fii",
            "Net_DII": "net_dii",
        },
    ).select(["date", "fii_buy", "fii_sell", "net_fii"])

    macro = _standardize_columns(
        macro_regime,
        {
            "Date": "date",
            "India_VIX": "india_vix",
            "US_VIX": "us_vix",
            "USD_INR": "usd_inr",
            "Brent_Crude": "brent_crude",
        },
    ).select(["date", "india_vix"])

    combined = flows.join(macro, on="date", how="inner").sort("date")
    if combined.height < 3:
        raise ValueError("At least three overlapping daily observations are required for regime detection.")

    enriched = combined.with_columns(
        _selling_magnitude_expression().alias("fii_net_selling"),
    )

    latest_window = enriched.tail(3).with_columns(
        pl.col("fii_net_selling").shift(2).alias("day_1_sell"),
        pl.col("fii_net_selling").shift(1).alias("day_2_sell"),
    )

    latest_row = latest_window.tail(1).select(
        [
            "date",
            "fii_net_selling",
            "india_vix",
            "day_1_sell",
            "day_2_sell",
        ]
    ).to_dicts()[0]

    day_1_sell = _to_float(latest_row.get("day_1_sell"))
    day_2_sell = _to_float(latest_row.get("day_2_sell"))
    day_3_sell = _to_float(latest_row.get("fii_net_selling"))
    india_vix_value = _to_float(latest_row.get("india_vix"))

    fii_exhaustion_setup = bool(
        day_1_sell is not None
        and day_2_sell is not None
        and day_3_sell is not None
        and day_1_sell > 5000
        and day_2_sell > 5000
        and day_3_sell > 5000
        and day_3_sell < day_2_sell < day_1_sell
        and india_vix_value is not None
        and india_vix_value > 20
    )

    bear_momentum = bool(
        not fii_exhaustion_setup
        and day_3_sell is not None
        and day_3_sell > 5000
        and india_vix_value is not None
        and india_vix_value > 20
    )

    if fii_exhaustion_setup:
        regime_state = "FII_EXHAUSTION_SETUP"
    elif bear_momentum:
        regime_state = "BEAR_MOMENTUM"
    else:
        regime_state = "CALM_BULL"

    return {
        "regime_state": regime_state,
        "signal_flags": {
            "fii_exhaustion_setup": fii_exhaustion_setup,
            "bear_momentum": bear_momentum,
            "calm_bull": regime_state == "CALM_BULL",
        },
        "latest_observation": {
            "date": latest_row.get("date"),
            "fii_net_selling": day_3_sell,
            "india_vix": india_vix_value,
        },
        "three_day_window": {
            "day_1_sell": day_1_sell,
            "day_2_sell": day_2_sell,
            "day_3_sell": day_3_sell,
        },
    }


def _standardize_columns(frame: pl.DataFrame, rename_map: dict[str, str]) -> pl.DataFrame:
    available = {source: target for source, target in rename_map.items() if source in frame.columns and source != target}
    standardized = frame.rename(available) if available else frame

    lowercase_candidates = {column: column.lower() for column in standardized.columns if column.lower() in rename_map.values() and column not in rename_map.values()}
    return standardized.rename(lowercase_candidates) if lowercase_candidates else standardized


def _selling_magnitude_expression() -> pl.Expr:
    net_sell_from_flow = pl.when(pl.col("fii_sell") > pl.col("fii_buy")).then(pl.col("fii_sell") - pl.col("fii_buy")).otherwise(0.0)
    net_sell_from_net_flow = pl.when(pl.col("net_fii") < 0).then(-pl.col("net_fii")).otherwise(0.0)
    return pl.max_horizontal(net_sell_from_flow, net_sell_from_net_flow)


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    if hasattr(value, "item"):
        value = value.item()
    if isinstance(value, float) and value != value:
        return None
    return float(value)


def detect_historical_regimes(
    institutional_flows: pl.DataFrame,
    macro_regime: pl.DataFrame,
) -> pl.DataFrame:
    """Compute historical rolling regime states for every date in the dataset.

    Returns a Polars DataFrame with columns ['date', 'regime_state'].
    """
    flows = _standardize_columns(
        institutional_flows,
        {
            "Date": "date",
            "FII_Buy": "fii_buy",
            "FII_Sell": "fii_sell",
            "DII_Buy": "dii_buy",
            "DII_Sell": "dii_sell",
            "Net_FII": "net_fii",
            "Net_DII": "net_dii",
        },
    ).select(["date", "fii_buy", "fii_sell", "net_fii"])

    macro = _standardize_columns(
        macro_regime,
        {
            "Date": "date",
            "India_VIX": "india_vix",
            "US_VIX": "us_vix",
            "USD_INR": "usd_inr",
            "Brent_Crude": "brent_crude",
        },
    ).select(["date", "india_vix"])

    combined = flows.join(macro, on="date", how="inner").sort("date")
    if combined.height == 0:
        return pl.DataFrame(schema={"date": pl.Date, "regime_state": pl.Utf8})

    enriched = combined.with_columns(
        _selling_magnitude_expression().alias("fii_net_selling")
    )

    fii_sell = pl.col("fii_net_selling")
    day_3 = fii_sell
    day_2 = fii_sell.shift(1)
    day_1 = fii_sell.shift(2)
    vix = pl.col("india_vix")

    fii_exhaustion_setup = (
        (day_1.is_not_null()) & (day_1 > 5000.0) &
        (day_2.is_not_null()) & (day_2 > 5000.0) &
        (day_3.is_not_null()) & (day_3 > 5000.0) &
        (day_3 < day_2) & (day_2 < day_1) &
        (vix.is_not_null()) & (vix > 20.0)
    )

    bear_momentum = (
        ~fii_exhaustion_setup &
        (day_3.is_not_null()) & (day_3 > 5000.0) &
        (vix.is_not_null()) & (vix > 20.0)
    )

    regime_state_expr = (
        pl.when(fii_exhaustion_setup).then(pl.lit("FII_EXHAUSTION_SETUP"))
        .when(bear_momentum).then(pl.lit("BEAR_MOMENTUM"))
        .otherwise(pl.lit("CALM_BULL"))
    )

    return enriched.with_columns(
        regime_state_expr.alias("regime_state")
    ).select(["date", "regime_state"])

