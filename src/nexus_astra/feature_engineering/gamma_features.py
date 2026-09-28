"""Polars-native gamma exposure analytics for NSE option-chain data."""

from __future__ import annotations

from dataclasses import dataclass

import polars as pl


@dataclass(frozen=True)
class GammaExposureConfig:
    """Configuration for gamma exposure analytics."""

    gamma_multiplier: float = 0.5
    pin_distance_threshold_pct: float = 1.0
    pin_oi_threshold_ratio: float = 0.40


class GammaExposure:
    """Compute dealer gamma exposure analytics from an NSE option-chain dataframe.

    Expected columns:
    - date
    - strike
    - call_oi
    - put_oi
    - spot or underlying_value
    - gamma (optional; defaults to 1.0)

    The implementation relies on Polars expressions, cumulative windows, and a
    cross join for max-pain calculation. No Python loops are used in the feature
    calculations.
    """

    def __init__(self, frame: pl.DataFrame, config: GammaExposureConfig | None = None) -> None:
        self._frame = frame.clone()
        self._config = config or GammaExposureConfig()

    def transform(self) -> pl.DataFrame:
        """Return a summary dataframe with zero gamma and pin-risk outputs."""

        frame = self._standardize_input(self._frame)
        required_columns = {"date", "strike", "call_oi", "put_oi"}
        missing_columns = sorted(required_columns.difference(frame.columns))
        if missing_columns:
            raise ValueError(f"Missing required option-chain columns: {', '.join(missing_columns)}")

        if "spot" not in frame.columns and "underlying_value" not in frame.columns:
            raise ValueError("Input dataframe must contain either 'spot' or 'underlying_value'.")

        if "gamma" not in frame.columns:
            frame = frame.with_columns(pl.lit(1.0).alias("gamma"))

        spot_expr = pl.coalesce([pl.col("spot"), pl.col("underlying_value")]).cast(pl.Float64)
        group_keys = ["date"]
        if "underlying" in frame.columns:
            group_keys.append("underlying")

        exposure_frame = (
            frame.with_columns(
                pl.col("date").cast(pl.Date),
                pl.col("strike").cast(pl.Float64),
                pl.col("call_oi").cast(pl.Float64),
                pl.col("put_oi").cast(pl.Float64),
                pl.col("gamma").cast(pl.Float64),
                spot_expr.alias("spot"),
                (pl.col("call_oi") + pl.col("put_oi")).alias("total_oi_at_strike"),
                (
                    pl.lit(self._config.gamma_multiplier)
                    * pl.col("gamma")
                    * pl.col("call_oi")
                    * ((spot_expr ** 2) / 100.0)
                ).alias("call_gamma_exposure"),
                (
                    pl.lit(self._config.gamma_multiplier)
                    * pl.col("gamma")
                    * pl.col("put_oi")
                    * ((spot_expr ** 2) / 100.0)
                ).alias("put_gamma_exposure"),
            )
            .sort(group_keys + ["strike"])
            .with_columns(
                (pl.col("put_gamma_exposure") - pl.col("call_gamma_exposure")).alias("net_gamma_exposure_per_strike"),
                (pl.col("strike") - pl.col("spot")).abs().truediv(pl.col("spot")).mul(100.0).alias("spot_distance_pct"),
            )
            .with_columns(
                pl.col("net_gamma_exposure_per_strike").cum_sum().over(group_keys).alias("cum_net_gamma"),
                pl.col("net_gamma_exposure_per_strike").sign().alias("net_gamma_per_strike_sign"),
            )
            .with_columns(
                pl.col("cum_net_gamma").shift(1).over(group_keys).alias("prev_cum_net_gamma"),
            )
            .with_columns(
                pl.when((pl.col("cum_net_gamma") <= 0.0).and_(pl.col("prev_cum_net_gamma") > 0.0))
                .then(pl.col("strike"))
                .otherwise(None)
                .alias("zero_gamma_candidate")
            )
        )

        zero_gamma_frame = (
            exposure_frame.group_by(group_keys)
            .agg(
                pl.col("cum_net_gamma").last().sign().alias("net_gamma_sign"),
                pl.col("zero_gamma_candidate").drop_nulls().first().alias("zero_gamma_level"),
                pl.col("spot").last().alias("spot"),
            )
        )

        max_pain_frame = self._compute_max_pain_frame(exposure_frame, group_keys)

        return (
            zero_gamma_frame.join(max_pain_frame, on=group_keys, how="left")
            .with_columns(
                pl.when(
                    pl.col("spot").is_not_null()
                    .and_(pl.col("spot") > 0.0)
                    .and_(
                        ((pl.col("spot") - pl.col("max_pain_strike")).abs() / pl.col("spot")) * 100.0
                        <= self._config.pin_distance_threshold_pct
                    )
                    .and_(pl.col("max_pain_strike_oi_share") > self._config.pin_oi_threshold_ratio)
                )
                .then(pl.lit(100.0))
                .otherwise(pl.lit(0.0))
                .alias("pin_risk_score")
            )
            .select(["date", "zero_gamma_level", "net_gamma_sign", "pin_risk_score"])
        )

    def compute(self) -> pl.DataFrame:
        """Alias for transform() for pipeline readability."""

        return self.transform()

    def _compute_max_pain_frame(self, exposure_frame: pl.DataFrame, group_keys: list[str]) -> pl.DataFrame:
        strikes = exposure_frame.select(group_keys + ["strike", "spot"]).rename({"strike": "candidate_strike"})
        options = exposure_frame.select(group_keys + ["strike", "call_oi", "put_oi"]).rename({"strike": "option_strike"})

        pain_surface = (
            strikes.join(options, on=group_keys, how="inner")
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

        per_candidate = (
            pain_surface.group_by(group_keys + ["candidate_strike"])
            .agg(
                pl.col("total_pain").sum().alias("total_pain"),
                pl.col("candidate_strike").first().alias("candidate_strike_reference"),
                pl.col("call_oi").sum().alias("call_oi_total"),
                pl.col("put_oi").sum().alias("put_oi_total"),
                pl.col("spot").last().alias("spot"),
            )
            .sort(group_keys + ["total_pain", "candidate_strike"])
        )

        totals = exposure_frame.group_by(group_keys).agg(
            pl.col("call_oi").sum().alias("group_call_oi"),
            pl.col("put_oi").sum().alias("group_put_oi"),
            pl.col("spot").last().alias("spot"),
        )

        return (
            per_candidate.group_by(group_keys)
            .agg(
                pl.col("candidate_strike").first().alias("max_pain_strike"),
                pl.col("call_oi_total").first().alias("max_pain_strike_call_oi"),
                pl.col("put_oi_total").first().alias("max_pain_strike_put_oi"),
                pl.col("spot").first().alias("spot"),
            )
            .join(totals, on=group_keys, how="left")
            .with_columns(
                (pl.col("max_pain_strike_call_oi") + pl.col("max_pain_strike_put_oi")).alias("max_pain_strike_total_oi"),
                (pl.col("group_call_oi") + pl.col("group_put_oi")).alias("group_total_oi"),
            )
            .with_columns(
                pl.when(pl.col("group_total_oi") > 0.0)
                .then(pl.col("max_pain_strike_total_oi") / pl.col("group_total_oi"))
                .otherwise(pl.lit(0.0))
                .alias("max_pain_strike_oi_share"),
                pl.when(pl.col("spot") > 0.0)
                .then(((pl.col("spot") - pl.col("max_pain_strike")).abs() / pl.col("spot")) * 100.0)
                .otherwise(pl.lit(0.0))
                .alias("spot_distance_from_max_pain_pct"),
            )
            .select(group_keys + ["max_pain_strike", "max_pain_strike_oi_share", "spot_distance_from_max_pain_pct"])
        )

    def _standardize_input(self, frame: pl.DataFrame) -> pl.DataFrame:
        rename_map = {
            "Date": "date",
            "Underlying": "underlying",
            "Strike": "strike",
            "Call_OI": "call_oi",
            "Put_OI": "put_oi",
            "Spot": "spot",
            "Underlying_Value": "underlying_value",
            "UnderlyingValue": "underlying_value",
            "Gamma": "gamma",
        }
        available_renames = {source: target for source, target in rename_map.items() if source in frame.columns and source != target}
        standardized = frame.rename(available_renames) if available_renames else frame

        if "date" not in standardized.columns and "expiry_date" in standardized.columns:
            standardized = standardized.rename({"expiry_date": "date"})

        return standardized


def gamma_exposure_summary(frame: pl.DataFrame) -> pl.DataFrame:
    """Convenience wrapper that returns the gamma exposure summary dataframe."""

    return GammaExposure(frame).transform()
