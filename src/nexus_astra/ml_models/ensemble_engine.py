"""Model training and walk-forward validation for NEXUS-ASTRA."""

from __future__ import annotations

from dataclasses import dataclass
from math import sqrt
from typing import Any

import numpy as np
import polars as pl
from sklearn.metrics import accuracy_score
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import OneHotEncoder
from xgboost import XGBClassifier


@dataclass(frozen=True)
class FoldResult:
    """Summary of a single walk-forward fold."""

    fold_id: int
    train_start: str
    train_end: str
    test_start: str
    test_end: str
    accuracy: float
    sharpe_ratio: float


class EnsembleEngine:
    """Train and validate a base XGBoost model with walk-forward splits."""

    def __init__(
        self,
        *,
        train_window: int = 252,
        test_window: int = 63,
        horizon: int = 5,
        random_state: int = 42,
        xgb_params: dict[str, Any] | None = None,
    ) -> None:
        self.train_window = train_window
        self.test_window = test_window
        self.horizon = horizon
        self.random_state = random_state
        self.xgb_params = xgb_params or {
            "n_estimators": 300,
            "max_depth": 4,
            "learning_rate": 0.05,
            "subsample": 0.8,
            "colsample_bytree": 0.8,
            "reg_alpha": 0.0,
            "reg_lambda": 1.0,
            "min_child_weight": 1.0,
            "objective": "binary:logistic",
            "eval_metric": "logloss",
            "tree_method": "hist",
            "random_state": random_state,
        }
        self.model: XGBClassifier | None = None
        self.meta_model: LogisticRegression | None = None
        self.meta_encoder: OneHotEncoder | None = None
        self.meta_feature_columns: list[str] | None = None

    def prepare_dataset(self, frame: pl.DataFrame) -> pl.DataFrame:
        """Create the binary target and drop rows without a valid forward label."""

        standardized = self._standardize_input(frame)
        if "date" not in standardized.columns:
            raise ValueError("Input dataframe must contain a 'date' column for walk-forward validation.")
        if "close" not in standardized.columns:
            raise ValueError("Input dataframe must contain a 'close' column.")

        return (
            standardized.sort("date")
            .with_columns(
                pl.col("close").cast(pl.Float64).alias("close"),
                pl.col("close").shift(-self.horizon).alias("future_close"),
                (pl.col("close").shift(-self.horizon) > pl.col("close"))
                .cast(pl.Int8)
                .alias("target_5d"),
                (pl.col("close").shift(-self.horizon) / pl.col("close") - 1.0).alias("future_return_5d"),
            )
            .drop_nulls(subset=["target_5d", "future_close"])
        )

    def train_xgboost_classifier(self, frame: pl.DataFrame) -> XGBClassifier:
        """Train an XGBoost classifier on the full prepared feature set."""

        dataset = self.prepare_dataset(frame)
        feature_columns = self._feature_columns(dataset)
        if not feature_columns:
            raise ValueError("No usable feature columns were found for training.")

        features = self._frame_to_matrix(dataset.select(feature_columns))
        target = dataset.get_column("target_5d").to_numpy()

        if len(np.unique(target)) < 2:
            raise ValueError("Training target must contain at least two classes.")

        model = XGBClassifier(**self.xgb_params)
        model.fit(features, target)
        self.model = model
        return model

    def walk_forward_validate(self, frame: pl.DataFrame) -> dict[str, Any]:
        """Run a 252-day train / 63-day test walk-forward validation without look-ahead bias."""

        dataset = self.prepare_dataset(frame)
        feature_columns = self._feature_columns(dataset)
        if not feature_columns:
            raise ValueError("No usable feature columns were found for validation.")

        if dataset.height < self.train_window + self.test_window:
            raise ValueError("Not enough rows for the requested walk-forward windows.")

        oos_predictions: list[int] = []
        oos_targets: list[int] = []
        oos_strategy_returns: list[float] = []
        fold_results: list[FoldResult] = []
        last_trained_model: XGBClassifier | None = None

        purge = 5
        embargo = 2
        fold_id = 1
        start_index = 0
        while start_index + self.train_window + purge + embargo + self.test_window <= dataset.height:
            train_start = start_index
            train_end = start_index + self.train_window
            test_start = train_end + purge + embargo
            test_end = test_start + self.test_window

            # Compute target shift AFTER split to prevent leakage
            train_slice = dataset.slice(train_start, self.train_window + self.horizon).with_columns(
                pl.col("close").shift(-self.horizon).alias("future_close")
            ).with_columns(
                (pl.col("future_close") > pl.col("close")).cast(pl.Int8).alias("target_5d")
            ).drop_nulls(subset=["target_5d"]).head(self.train_window)
            
            has_low = "low" in dataset.columns
            low_col = pl.col("low") if has_low else pl.col("close")
            
            test_slice = dataset.slice(test_start, self.test_window + self.horizon).with_columns(
                pl.col("close").shift(-self.horizon).alias("future_close"),
                low_col.rolling_min(window_size=self.horizon).shift(-self.horizon).alias("future_min_low")
            ).with_columns(
                (pl.col("future_close") > pl.col("close")).cast(pl.Int8).alias("target_5d"),
                (pl.col("future_close") / pl.col("close") - 1.0).alias("future_return_5d")
            ).drop_nulls(subset=["target_5d"]).head(self.test_window)

            x_train = self._frame_to_matrix(train_slice.select(feature_columns))
            y_train = train_slice.get_column("target_5d").to_numpy()
            x_test = self._frame_to_matrix(test_slice.select(feature_columns))
            y_test = test_slice.get_column("target_5d").to_numpy()

            model, fold_predictions = self._fit_and_predict(x_train, y_train, x_test)
            last_trained_model = model

            binary_predictions = (fold_predictions > 0.5).astype(int)
            fold_accuracy = accuracy_score(y_test, binary_predictions)
            fold_strategy_returns = self._strategy_returns(test_slice, fold_predictions)
            fold_sharpe = self._sharpe_ratio(fold_strategy_returns)

            oos_predictions.extend(binary_predictions.tolist())
            oos_targets.extend(y_test.tolist())
            oos_strategy_returns.extend(fold_strategy_returns.tolist())

            fold_results.append(
                FoldResult(
                    fold_id=fold_id,
                    train_start=str(train_slice.get_column("date")[0]),
                    train_end=str(train_slice.get_column("date")[-1]),
                    test_start=str(test_slice.get_column("date")[0]),
                    test_end=str(test_slice.get_column("date")[-1]),
                    accuracy=float(fold_accuracy),
                    sharpe_ratio=float(fold_sharpe),
                )
            )

            fold_id += 1
            start_index += self.test_window

        if not oos_predictions:
            raise ValueError("Walk-forward validation produced no out-of-sample predictions.")

        self.model = last_trained_model
        overall_accuracy = accuracy_score(oos_targets, oos_predictions)
        overall_sharpe = self._sharpe_ratio(np.asarray(oos_strategy_returns, dtype=float))

        return {
            "out_of_sample_accuracy": float(overall_accuracy),
            "out_of_sample_sharpe": float(overall_sharpe),
            "n_oos_predictions": len(oos_predictions),
            "folds": [fold.__dict__ for fold in fold_results],
        }

    def train_meta_learner(
        self,
        frame: pl.DataFrame,
        macro_state: str,
    ) -> LogisticRegression:
        """Train the logistic meta-learner on XGBoost probabilities and macro regime state."""

        dataset = self.prepare_dataset(frame)
        feature_columns = self._feature_columns(dataset)
        if not feature_columns:
            raise ValueError("No usable feature columns were found for meta-learner training.")

        x_matrix = self._frame_to_matrix(dataset.select(feature_columns))
        y_target = dataset.get_column("target_5d").to_numpy()

        xgb_model = self.model or self.train_xgboost_classifier(frame)
        xgb_probability = xgb_model.predict_proba(x_matrix)[:, 1]
        regime_features = self._macro_state_one_hot_dataset(macro_state, dataset.height)

        meta_features = np.column_stack([xgb_probability, regime_features])
        meta_model = LogisticRegression(max_iter=1000, random_state=self.random_state)
        meta_model.fit(meta_features, y_target)
        self.meta_model = meta_model
        return meta_model

    def composite_signal_score(
        self,
        frame: pl.DataFrame,
        macro_state: str,
    ) -> pl.DataFrame:
        """Return composite scores in the 0-100 range with a strict > 75 signal filter."""

        dataset = self.prepare_dataset(frame)
        feature_columns = self._feature_columns(dataset)
        if not feature_columns:
            raise ValueError("No usable feature columns were found for scoring.")

        xgb_model = self.model or self.train_xgboost_classifier(frame)
        meta_model = self.meta_model or self.train_meta_learner(frame, macro_state)

        x_matrix = self._frame_to_matrix(dataset.select(feature_columns))
        xgb_probability = xgb_model.predict_proba(x_matrix)[:, 1]
        regime_features = self._macro_state_one_hot_dataset(macro_state, dataset.height)
        meta_features = np.column_stack([xgb_probability, regime_features])

        composite_probability = meta_model.predict_proba(meta_features)[:, 1]
        composite_score = np.clip(composite_probability * 100.0, 0.0, 100.0)

        result = dataset.with_columns(
            pl.Series("xgb_probability", xgb_probability),
            pl.Series("macro_regime_state", [macro_state] * dataset.height),
            pl.Series("composite_signal_score", composite_score),
            pl.Series("signal_allowed", composite_score > 75.0),
        )

        return result.filter(pl.col("signal_allowed"))

    def fit_meta_learner(self, frame: pl.DataFrame, macro_regime_states: pl.DataFrame) -> LogisticRegression:
        """Train the LogisticRegression meta-learner on OOF XGBoost probabilities and regime state dummies."""

        meta_frame = self._build_meta_training_frame(frame, macro_regime_states)
        if meta_frame.is_empty():
            raise ValueError("Meta-learner training produced no rows.")

        feature_matrix, target = self._meta_matrix_and_target(meta_frame, fit_encoder=True)
        if len(np.unique(target)) < 2:
            raise ValueError("Meta-learner target must contain at least two classes.")

        meta_model = LogisticRegression(max_iter=1000, class_weight="balanced", random_state=self.random_state)
        meta_model.fit(feature_matrix, target)
        self.meta_model = meta_model

        # Fit a full-sample base model for live signal scoring after the OOF meta fit.
        self.train_xgboost_classifier(frame)
        return meta_model

    def score_composite_signals(
        self,
        frame: pl.DataFrame,
        macro_regime_states: pl.DataFrame,
        *,
        threshold: float = 75.0,
    ) -> pl.DataFrame:
        """Return only the high-conviction signals where Composite Signal Score is above the threshold."""

        if self.meta_model is None:
            self.fit_meta_learner(frame, macro_regime_states)

        scored = self._build_composite_signal_frame(frame, macro_regime_states)
        return scored.filter(pl.col("composite_signal_score") > threshold)

    def _build_meta_training_frame(self, frame: pl.DataFrame, macro_regime_states: pl.DataFrame) -> pl.DataFrame:
        prepared = self.prepare_dataset(frame)
        regimes = self._standardize_macro_states(macro_regime_states)
        combined = prepared.join(regimes, on="date", how="inner").sort("date")

        feature_columns = self._feature_columns(combined)
        if not feature_columns:
            raise ValueError("No usable feature columns were found for meta-learner training.")

        if combined.height < self.train_window + self.test_window:
            raise ValueError("Not enough rows for walk-forward meta-learner training.")

        meta_frames: list[pl.DataFrame] = []
        purge = 5
        embargo = 2
        start_index = 0
        while start_index + self.train_window + purge + embargo + self.test_window <= combined.height:
            train_start = start_index
            train_end = start_index + self.train_window
            test_start = train_end + purge + embargo
            test_end = test_start + self.test_window

            train_slice = combined.slice(train_start, self.train_window + self.horizon).with_columns(
                pl.col("close").shift(-self.horizon).alias("future_close")
            ).with_columns((pl.col("future_close") > pl.col("close")).cast(pl.Int8).alias("target_5d")).drop_nulls(subset=["target_5d"]).head(self.train_window)
            
            test_slice = combined.slice(test_start, self.test_window + self.horizon).with_columns(
                pl.col("close").shift(-self.horizon).alias("future_close")
            ).with_columns((pl.col("future_close") > pl.col("close")).cast(pl.Int8).alias("target_5d")).drop_nulls(subset=["target_5d"]).head(self.test_window)

            x_train = self._frame_to_matrix(train_slice.select(feature_columns))
            y_train = train_slice.get_column("target_5d").to_numpy()
            x_test = self._frame_to_matrix(test_slice.select(feature_columns))

            _, predicted_probabilities = self._fit_and_predict_proba(x_train, y_train, x_test)

            meta_frames.append(
                test_slice.select(["date", "target_5d", "regime_state"]).with_columns(
                    pl.Series("xgb_probability", predicted_probabilities)
                )
            )

            start_index += self.test_window

        if not meta_frames:
            return pl.DataFrame(schema={"date": pl.Date, "target_5d": pl.Int8, "regime_state": pl.Utf8, "xgb_probability": pl.Float64})

        return pl.concat(meta_frames, how="vertical").sort("date")

    def _build_composite_signal_frame(self, frame: pl.DataFrame, macro_regime_states: pl.DataFrame) -> pl.DataFrame:
        if self.meta_model is None:
            raise ValueError("Meta-learner has not been trained. Call fit_meta_learner() first.")

        if self.model is None:
            self.train_xgboost_classifier(frame)

        prepared = self.prepare_dataset(frame)
        regimes = self._standardize_macro_states(macro_regime_states)
        combined = prepared.join(regimes, on="date", how="inner").sort("date")

        feature_columns = self._feature_columns(combined)
        if not feature_columns:
            raise ValueError("No usable feature columns were found for signal scoring.")

        x_base = self._frame_to_matrix(combined.select(feature_columns))
        xgb_probabilities = self._predict_probabilities(self.model, x_base)

        scoring_frame = combined.select(["date", "target_5d", "regime_state"]).with_columns(
            pl.Series("xgb_probability", xgb_probabilities)
        )
        feature_matrix, _ = self._meta_matrix_and_target(scoring_frame, fit_encoder=False)
        composite_probabilities = self.meta_model.predict_proba(feature_matrix)[:, 1]

        return scoring_frame.with_columns(
            pl.Series("composite_signal_score", composite_probabilities * 100.0)
        )

    def _fit_and_predict(
        self,
        x_train: np.ndarray,
        y_train: np.ndarray,
        x_test: np.ndarray,
    ) -> tuple[Any, np.ndarray]:
        if len(np.unique(y_train)) < 2:
            majority_class = int(np.round(float(np.mean(y_train))))

            class ConstantClassifier:
                def __init__(self, constant: int) -> None:
                    self.constant = constant

                def predict(self, x: np.ndarray) -> np.ndarray:
                    return np.full(shape=(x.shape[0],), fill_value=self.constant, dtype=int)

            model = ConstantClassifier(majority_class)  # type: ignore[assignment]
            predictions = model.predict(x_test)
            return model, predictions

        model = XGBClassifier(**self.xgb_params)
        model.fit(x_train, y_train)
        predictions = model.predict_proba(x_test)[:, 1]
        return model, predictions

    def _fit_and_predict_proba(
        self,
        x_train: np.ndarray,
        y_train: np.ndarray,
        x_test: np.ndarray,
    ) -> tuple[Any, np.ndarray]:
        if len(np.unique(y_train)) < 2:
            majority_class = int(np.round(float(np.mean(y_train))))

            class ConstantProbabilityModel:
                def __init__(self, constant: int) -> None:
                    self.constant = constant

                def predict_proba(self, x: np.ndarray) -> np.ndarray:
                    positive_probability = float(self.constant)
                    negative_probability = 1.0 - positive_probability
                    return np.column_stack(
                        [
                            np.full(shape=(x.shape[0],), fill_value=negative_probability, dtype=float),
                            np.full(shape=(x.shape[0],), fill_value=positive_probability, dtype=float),
                        ]
                    )

            model = ConstantProbabilityModel(majority_class)
            return model, model.predict_proba(x_test)[:, 1]

        model = XGBClassifier(**self.xgb_params)
        model.fit(x_train, y_train)
        predictions = model.predict_proba(x_test)[:, 1]
        return model, predictions

    def _strategy_returns(self, test_slice: pl.DataFrame, proba: np.ndarray) -> np.ndarray:
        forward_returns = test_slice.get_column("future_return_5d").to_numpy()
        future_min_low = test_slice.get_column("future_min_low").to_numpy()
        close_prices = test_slice.get_column("close").to_numpy()
        
        positions = np.where(proba > 0.5, 1.0, -1.0)
        
        stop_pct = 0.02
        long_stops = close_prices * (1 - stop_pct)
        
        returns = np.zeros_like(forward_returns)
        for i in range(len(positions)):
            if positions[i] == 1.0:
                if future_min_low[i] < long_stops[i]:
                    returns[i] = -stop_pct
                else:
                    returns[i] = forward_returns[i]
            else:
                # We do not have high prices for shorts easily, fallback to just bounding loss for symmetry if wanted,
                # but "if low < stop in holding window" is only physically meaningful for longs.
                # Assuming standard returns for shorts.
                returns[i] = max(-stop_pct, positions[i] * forward_returns[i])
                    
        return returns

    @staticmethod
    def _sharpe_ratio(returns: np.ndarray) -> float:
        returns = np.asarray(returns, dtype=float)
        if returns.size == 0:
            return 0.0

        std_dev = returns.std(ddof=1) if returns.size > 1 else 0.0
        if std_dev == 0.0 or np.isnan(std_dev):
            return 0.0

        return float((returns.mean() / std_dev) * sqrt(252.0 / 5.0))

    def _standardize_input(self, frame: pl.DataFrame) -> pl.DataFrame:
        rename_candidates = {
            "Date": "date",
            "Open": "open",
            "High": "high",
            "Low": "low",
            "Close": "close",
            "Volume": "volume",
            "VWAP": "vwap",
        }
        available = {source: target for source, target in rename_candidates.items() if source in frame.columns and source != target}
        return frame.rename(available) if available else frame

    def _standardize_macro_states(self, frame: pl.DataFrame) -> pl.DataFrame:
        rename_candidates = {
            "Date": "date",
            "Regime_State": "regime_state",
            "RegimeState": "regime_state",
            "regime": "regime_state",
        }
        available = {source: target for source, target in rename_candidates.items() if source in frame.columns and source != target}
        standardized = frame.rename(available) if available else frame

        if "date" not in standardized.columns:
            raise ValueError("Macro regime state frame must contain a 'date' column.")
        if "regime_state" not in standardized.columns:
            raise ValueError("Macro regime state frame must contain a 'regime_state' column.")

        return standardized.select(["date", "regime_state"]).sort("date")

    def _feature_columns(self, frame: pl.DataFrame) -> list[str]:
        excluded = {
            "date",
            "target_5d",
            "future_close",
            "future_return_5d",
        }
        feature_columns: list[str] = []
        for column, dtype in frame.schema.items():
            if column in excluded:
                continue
            if dtype in pl.NUMERIC_DTYPES or dtype == pl.Boolean:
                feature_columns.append(column)
        return feature_columns

    @staticmethod
    def _frame_to_matrix(frame: pl.DataFrame) -> np.ndarray:
        return frame.select([pl.all().cast(pl.Float64)]).to_numpy()

    def _meta_matrix_and_target(self, frame: pl.DataFrame, *, fit_encoder: bool) -> tuple[np.ndarray, np.ndarray]:
        xgb_probability = frame.get_column("xgb_probability").cast(pl.Float64).to_numpy().reshape(-1, 1)
        regime_values = frame.get_column("regime_state").fill_null("UNKNOWN").cast(pl.Utf8).to_numpy().reshape(-1, 1)
        regime_matrix = self._encode_regime_states(regime_values, fit_encoder=fit_encoder)
        feature_matrix = np.hstack([xgb_probability, regime_matrix])
        target = frame.get_column("target_5d").to_numpy() if "target_5d" in frame.columns else np.empty(shape=(frame.height,), dtype=int)
        return feature_matrix, target

    def _encode_regime_states(self, regime_values: np.ndarray, *, fit_encoder: bool) -> np.ndarray:
        encoder = self.meta_encoder
        if fit_encoder or encoder is None:
            try:
                encoder = OneHotEncoder(handle_unknown="ignore", sparse_output=False)
            except TypeError:
                encoder = OneHotEncoder(handle_unknown="ignore", sparse=False)
            regime_matrix = encoder.fit_transform(regime_values)
            self.meta_encoder = encoder
            self.meta_feature_columns = ["xgb_probability", *encoder.get_feature_names_out(["regime_state"]).tolist()]
            return regime_matrix

        return encoder.transform(regime_values)

    @staticmethod
    def _predict_probabilities(model: Any, x_values: np.ndarray) -> np.ndarray:
        if hasattr(model, "predict_proba"):
            probabilities = model.predict_proba(x_values)
            return probabilities[:, 1]
        predictions = model.predict(x_values)
        return np.asarray(predictions, dtype=float)

    def _macro_state_one_hot_dataset(self, macro_state: str, height: int) -> np.ndarray:
        regime_values = np.full((height, 1), macro_state, dtype=object)
        return self._encode_regime_states(regime_values, fit_encoder=False)

