from __future__ import annotations

import os
from pathlib import Path

import numpy as np
import pandas as pd

def _resolve_model_dir() -> Path:
    override = (os.getenv("HACCP_SENSOR_MODEL_DIR", "") or "").strip()
    if override:
        return Path(override).expanduser().resolve()
    return Path(__file__).resolve().parent


MODEL_DIR = _resolve_model_dir()
SCALER_PATH = MODEL_DIR / "robust_scaler.pkl"
TRACK1_MODEL_PATH = MODEL_DIR / "track1_inception_fold5.keras"
TRACK2_MODEL_PATH = MODEL_DIR / "track2_inception_fold5.keras"
OPTIMAL_THRESHOLD = 0.23
DROP_COLUMNS = {"batch_id", "timestamp", "contamination", "state"}
AUTO_PROCESS_BASE_COLUMNS = [
    "T",
    "pH",
    "Kappa",
    "Mu",
    "Tau",
    "Q_in",
    "Q_out",
    "P",
    "dTdt",
    "ccp_hold_time_ok",
    "ccp_hold_temp_ok",
]
AUTO_TIME_FEATURE_COLUMNS = [
    "ts_year",
    "ts_month",
    "ts_day",
    "ts_hour",
    "ts_minute",
    "ts_second",
    "ts_weekday",
    "ts_is_weekend",
]
EXPECTED_PROCESS_FEATURE_COLUMNS = AUTO_PROCESS_BASE_COLUMNS + AUTO_TIME_FEATURE_COLUMNS

_SCALER = None
_MODEL_TRACK1 = None
_MODEL_TRACK2 = None
_TF = None
_LOAD_ERROR = None
_LOAD_ATTEMPTED = False


def binary_focal_loss(gamma=2.0, alpha=0.25):
    def focal_loss_fn(y_true, y_pred):
        y_true = _TF.cast(y_true, _TF.float32)
        y_pred = _TF.clip_by_value(y_pred, _TF.keras.backend.epsilon(), 1.0 - _TF.keras.backend.epsilon())
        p_t = y_true * y_pred + (1 - y_true) * (1 - y_pred)
        alpha_factor = y_true * alpha + (1 - y_true) * (1 - alpha)
        modulating_factor = _TF.pow(1.0 - p_t, gamma)
        loss = -alpha_factor * modulating_factor * _TF.math.log(p_t)
        return _TF.reduce_mean(loss)

    return focal_loss_fn


def _load_assets_once():
    global _SCALER, _MODEL_TRACK1, _MODEL_TRACK2, _TF, _LOAD_ERROR, _LOAD_ATTEMPTED

    if _SCALER is not None and _MODEL_TRACK1 is not None and _MODEL_TRACK2 is not None:
        return
    if _LOAD_ERROR is not None:
        return

    _LOAD_ATTEMPTED = True

    try:
        # Reduce TF memory/log overhead on tiny hosts (e.g. Render free 512MB).
        os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "3")
        os.environ.setdefault("CUDA_VISIBLE_DEVICES", "-1")

        import joblib
        import tensorflow as tf
        from tensorflow.keras.models import load_model

        try:
            tf.config.threading.set_inter_op_parallelism_threads(1)
            tf.config.threading.set_intra_op_parallelism_threads(1)
        except Exception:
            pass

        missing_paths = [
            str(path)
            for path in (SCALER_PATH, TRACK1_MODEL_PATH)
            if not path.exists()
        ]
        if missing_paths:
            raise FileNotFoundError(f"Missing inference assets: {', '.join(missing_paths)}")

        _TF = tf
        _SCALER = joblib.load(SCALER_PATH)
        # Only load track1 here; track2 is loaded on demand to halve baseline RAM.
        _MODEL_TRACK1 = load_model(
            TRACK1_MODEL_PATH,
            custom_objects={"focal_loss_fn": binary_focal_loss(gamma=2.0, alpha=0.33)},
            compile=False,
        )
    except Exception as exc:
        _LOAD_ERROR = str(exc)


def _load_track2_once():
    global _MODEL_TRACK2, _LOAD_ERROR
    if _MODEL_TRACK2 is not None or _LOAD_ERROR is not None:
        return
    try:
        from tensorflow.keras.models import load_model
        if not TRACK2_MODEL_PATH.exists():
            raise FileNotFoundError(f"Missing track2 asset: {TRACK2_MODEL_PATH}")
        _MODEL_TRACK2 = load_model(
            TRACK2_MODEL_PATH,
            custom_objects={"focal_loss_fn": binary_focal_loss(gamma=3.0, alpha=0.5)},
            compile=False,
        )
    except Exception as exc:
        _LOAD_ERROR = str(exc)


def get_inference_status(attempt_load: bool = False) -> dict:
    if attempt_load:
        _load_assets_once()

    return {
        # track1 readiness reflects baseline serving capability;
        # track2 is loaded lazily when contamination is suspected.
        "ready": _SCALER is not None and _MODEL_TRACK1 is not None,
        "error": _LOAD_ERROR,
        "load_attempted": _LOAD_ATTEMPTED,
        "model_dir": str(MODEL_DIR),
        "assets_present": all(path.exists() for path in (SCALER_PATH, TRACK1_MODEL_PATH, TRACK2_MODEL_PATH)),
    }


def _validate_input_dataframe(raw_df: pd.DataFrame) -> None:
    if raw_df is None or raw_df.empty:
        raise ValueError("Uploaded CSV is empty.")


def _get_expected_feature_count() -> int:
    scaler_feature_count = getattr(_SCALER, "n_features_in_", None)
    if scaler_feature_count is not None:
        return int(scaler_feature_count)

    model_shape = getattr(_MODEL_TRACK1, "input_shape", None)
    if model_shape and len(model_shape) >= 2 and model_shape[1] is not None:
        return int(model_shape[1])

    raise RuntimeError("Unable to determine expected feature count from loaded inference assets.")


def _build_relative_datetime(frame: pd.DataFrame) -> pd.Series:
    if "datetime" in frame.columns:
        datetime_series = pd.to_datetime(frame["datetime"], errors="coerce")
        if datetime_series.notna().any():
            return datetime_series

    if "timestamp" not in frame.columns:
        raise ValueError("Uploaded CSV must include either 'datetime' or 'timestamp' to auto-build process features.")

    timestamp_numeric = pd.to_numeric(frame["timestamp"], errors="coerce")
    if timestamp_numeric.notna().all():
        latest_timestamp = timestamp_numeric.max()
        latest_datetime = pd.Timestamp.now().floor("min")
        return latest_datetime - pd.to_timedelta(latest_timestamp - timestamp_numeric, unit="s")

    datetime_series = pd.to_datetime(frame["timestamp"], errors="coerce")
    if datetime_series.notna().any():
        return datetime_series

    raise ValueError("Unable to interpret uploaded timestamp values for automatic feature generation.")


def _prepare_feature_frame(raw_df: pd.DataFrame, expected_feature_count: int):
    frame = raw_df.copy()
    direct_feature_cols = [column for column in frame.columns if column not in DROP_COLUMNS]

    if len(direct_feature_cols) == expected_feature_count and all(
        pd.api.types.is_numeric_dtype(frame[column]) for column in direct_feature_cols
    ):
        return frame[direct_feature_cols].apply(pd.to_numeric, errors="raise"), list(direct_feature_cols), "explicit-19-feature"

    missing_base_columns = [column for column in AUTO_PROCESS_BASE_COLUMNS if column not in frame.columns]
    if missing_base_columns:
        raise ValueError(
            "Uploaded CSV does not match the model input. "
            f"Expected either {expected_feature_count} numeric feature columns or the raw process columns {AUTO_PROCESS_BASE_COLUMNS}."
        )

    datetime_series = _build_relative_datetime(frame)
    feature_frame = frame[AUTO_PROCESS_BASE_COLUMNS].copy()
    feature_frame["ts_year"] = datetime_series.dt.year
    feature_frame["ts_month"] = datetime_series.dt.month
    feature_frame["ts_day"] = datetime_series.dt.day
    feature_frame["ts_hour"] = datetime_series.dt.hour
    feature_frame["ts_minute"] = datetime_series.dt.minute
    feature_frame["ts_second"] = datetime_series.dt.second
    feature_frame["ts_weekday"] = datetime_series.dt.weekday
    feature_frame["ts_is_weekend"] = (datetime_series.dt.weekday >= 5).astype(int)

    feature_frame = feature_frame[EXPECTED_PROCESS_FEATURE_COLUMNS].apply(pd.to_numeric, errors="raise")
    if feature_frame.shape[1] != expected_feature_count:
        raise ValueError(
            f"Auto-generated process feature count {feature_frame.shape[1]} does not match model expectation {expected_feature_count}."
        )
    return feature_frame, list(feature_frame.columns), "process-csv-auto-feature-build"


def preprocess_for_inference(raw_df: pd.DataFrame):
    _load_assets_once()
    if _LOAD_ERROR is not None:
        raise RuntimeError(_LOAD_ERROR)

    _validate_input_dataframe(raw_df)
    expected_feature_count = _get_expected_feature_count()
    numeric_frame, feature_cols, input_mode = _prepare_feature_frame(raw_df, expected_feature_count)
    if len(numeric_frame) == 1:
        feature_vector = numeric_frame.iloc[0].to_numpy(dtype=float)
        aggregation_mode = f"{input_mode}:single-row direct"
    else:
        feature_vector = numeric_frame.median(axis=0).to_numpy(dtype=float)
        aggregation_mode = f"{input_mode}:column-median profile"

    scaled_data = _SCALER.transform(feature_vector.reshape(1, expected_feature_count))
    input_3d = scaled_data.reshape(1, expected_feature_count, 1)
    scaled_vector = scaled_data.reshape(expected_feature_count)
    top_indices = np.argsort(np.abs(scaled_vector))[::-1][:5]
    top_deviation_features = [
        {
            "name": feature_cols[index],
            "scaled_score": float(scaled_vector[index]),
            "raw_value": float(feature_vector[index]),
        }
        for index in top_indices
    ]
    return input_3d, feature_cols, aggregation_mode, top_deviation_features


def predict_contamination(raw_df: pd.DataFrame) -> dict:
    input_3d, feature_cols, aggregation_mode, top_deviation_features = preprocess_for_inference(raw_df)

    track1_score = float(_MODEL_TRACK1.predict(input_3d, verbose=0)[0][0])
    if track1_score < 0.5:
        label = "no"
        track2_score = 0.0
    else:
        _load_track2_once()
        if _LOAD_ERROR is not None or _MODEL_TRACK2 is None:
            raise RuntimeError(_LOAD_ERROR or "track2 model unavailable")
        track2_score = float(_MODEL_TRACK2.predict(input_3d, verbose=0)[0][0])
        label = "bio" if track2_score < OPTIMAL_THRESHOLD else "chem"

    return {
        "label": label,
        "track1_score": track1_score,
        "track2_score": track2_score,
        "threshold": OPTIMAL_THRESHOLD,
        "rows": int(len(raw_df)),
        "feature_count": int(len(feature_cols)),
        "feature_columns": feature_cols,
        "aggregation_mode": aggregation_mode,
        "top_deviation_features": top_deviation_features,
    }
