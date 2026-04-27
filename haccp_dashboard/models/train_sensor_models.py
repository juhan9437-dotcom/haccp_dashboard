from __future__ import annotations

import argparse
import os
from pathlib import Path

import numpy as np
import pandas as pd


def _build_relative_datetime(timestamp_series: pd.Series) -> pd.Series:
    timestamp_numeric = pd.to_numeric(timestamp_series, errors="coerce").fillna(0.0)
    latest_timestamp = float(timestamp_numeric.max())
    latest_datetime = pd.Timestamp.now().floor("min")
    return latest_datetime - pd.to_timedelta(latest_timestamp - timestamp_numeric, unit="s")


def _build_feature_frame(raw_df: pd.DataFrame) -> pd.DataFrame:
    required = [
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
        "timestamp",
    ]
    missing = [col for col in required if col not in raw_df.columns]
    if missing:
        raise ValueError(f"Missing required columns: {', '.join(missing)}")

    datetime_series = _build_relative_datetime(raw_df["timestamp"])
    frame = raw_df.copy()

    feature_frame = frame[
        [
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
    ].apply(pd.to_numeric, errors="coerce")

    feature_frame["ts_year"] = datetime_series.dt.year
    feature_frame["ts_month"] = datetime_series.dt.month
    feature_frame["ts_day"] = datetime_series.dt.day
    feature_frame["ts_hour"] = datetime_series.dt.hour
    feature_frame["ts_minute"] = datetime_series.dt.minute
    feature_frame["ts_second"] = datetime_series.dt.second
    feature_frame["ts_weekday"] = datetime_series.dt.weekday
    feature_frame["ts_is_weekend"] = (datetime_series.dt.weekday >= 5).astype(int)

    return feature_frame.apply(pd.to_numeric, errors="coerce").fillna(0.0)


def _build_batch_level_dataset(df: pd.DataFrame) -> tuple[np.ndarray, np.ndarray, np.ndarray, list[str]]:
    if "batch_id" not in df.columns:
        raise ValueError("CSV must include 'batch_id'.")
    if "contamination" not in df.columns:
        raise ValueError("CSV must include 'contamination'.")

    df = df.copy()
    df["contamination"] = df["contamination"].astype(str).str.strip().str.lower()
    df["is_contaminated"] = (df["contamination"] != "no").astype(int)
    df["is_chem"] = (df["contamination"] == "chem").astype(int)
    df["is_bio"] = (df["contamination"] == "bio").astype(int)

    feature_frame = _build_feature_frame(df)
    feature_cols = list(feature_frame.columns)

    df_features = pd.concat([df[["batch_id", "contamination", "is_contaminated", "is_chem", "is_bio"]], feature_frame], axis=1)
    grouped = df_features.groupby("batch_id", sort=True)

    X = grouped[feature_cols].median().to_numpy(dtype=np.float32)
    y_track1 = grouped["is_contaminated"].max().to_numpy(dtype=np.int32)

    contamination_mode = grouped["contamination"].agg(lambda s: s.value_counts().idxmax())
    mask_contaminated = contamination_mode != "no"
    contaminated_ids = contamination_mode.index[mask_contaminated].to_numpy(dtype=int)

    y_track2 = contamination_mode.loc[contaminated_ids].map({"bio": 0, "chem": 1}).astype(int).to_numpy(dtype=np.int32)

    return X, y_track1, y_track2, feature_cols


def _train_binary_model(
    X_train: np.ndarray,
    y_train: np.ndarray,
    X_val: np.ndarray,
    y_val: np.ndarray,
    *,
    gamma: float,
    alpha: float,
    seed: int,
    epochs: int,
    batch_size: int,
):
    import tensorflow as tf

    tf.keras.utils.set_random_seed(seed)

    def focal_loss_fn(y_true, y_pred):
        y_true = tf.cast(y_true, tf.float32)
        y_pred = tf.clip_by_value(y_pred, tf.keras.backend.epsilon(), 1.0 - tf.keras.backend.epsilon())
        p_t = y_true * y_pred + (1 - y_true) * (1 - y_pred)
        alpha_factor = y_true * alpha + (1 - y_true) * (1 - alpha)
        modulating_factor = tf.pow(1.0 - p_t, gamma)
        loss = -alpha_factor * modulating_factor * tf.math.log(p_t)
        return tf.reduce_mean(loss)

    inputs = tf.keras.Input(shape=(X_train.shape[1], 1))
    x = tf.keras.layers.Conv1D(32, 3, padding="same", activation="relu")(inputs)
    x = tf.keras.layers.Conv1D(64, 3, padding="same", activation="relu")(x)
    x = tf.keras.layers.GlobalMaxPooling1D()(x)
    x = tf.keras.layers.Dropout(0.25)(x)
    x = tf.keras.layers.Dense(64, activation="relu")(x)
    x = tf.keras.layers.Dropout(0.2)(x)
    outputs = tf.keras.layers.Dense(1, activation="sigmoid")(x)
    model = tf.keras.Model(inputs=inputs, outputs=outputs)

    model.compile(
        optimizer=tf.keras.optimizers.Adam(learning_rate=1e-3),
        loss=focal_loss_fn,
        metrics=[tf.keras.metrics.AUC(name="auc"), tf.keras.metrics.BinaryAccuracy(name="acc")],
    )

    callbacks = [
        tf.keras.callbacks.EarlyStopping(monitor="val_auc", mode="max", patience=6, restore_best_weights=True),
        tf.keras.callbacks.ReduceLROnPlateau(monitor="val_auc", mode="max", patience=3, factor=0.5, min_lr=1e-5),
    ]

    model.fit(
        X_train,
        y_train,
        validation_data=(X_val, y_val),
        epochs=int(epochs),
        batch_size=int(batch_size),
        verbose=2,
        callbacks=callbacks,
    )

    return model


def main():
    parser = argparse.ArgumentParser(description="Train sensor (CSV) deep learning models for contamination inference.")
    parser.add_argument(
        "--csv",
        dest="csv_path",
        default="",
        help="Path to batch_150_contaminated_onlylabel_final_v4.csv (default: project common path).",
    )
    parser.add_argument(
        "--output-dir",
        dest="output_dir",
        default="",
        help="Directory to write assets (robust_scaler.pkl, track1_*.keras, track2_*.keras). Default: haccp_dashboard/models",
    )
    parser.add_argument("--epochs", type=int, default=35)
    parser.add_argument("--batch-size", type=int, default=32)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--val-split", type=float, default=0.2)
    args = parser.parse_args()

    from haccp_dashboard.lib.main_helpers import resolve_process_csv_path

    csv_path = Path(args.csv_path).expanduser() if str(args.csv_path).strip() else Path(resolve_process_csv_path())
    output_dir = Path(args.output_dir).expanduser() if str(args.output_dir).strip() else Path(__file__).resolve().parent
    output_dir.mkdir(parents=True, exist_ok=True)

    df = pd.read_csv(csv_path, encoding="utf-8-sig")
    X_all, y_track1_all, y_track2_all, feature_cols = _build_batch_level_dataset(df)

    # Deterministic split.
    rng = np.random.default_rng(int(args.seed))
    indices = np.arange(len(X_all))
    rng.shuffle(indices)
    val_size = max(1, int(len(indices) * float(args.val_split)))
    val_idx = indices[:val_size]
    train_idx = indices[val_size:]

    from sklearn.preprocessing import RobustScaler
    import joblib

    scaler = RobustScaler()
    X_train_raw = X_all[train_idx]
    X_val_raw = X_all[val_idx]
    scaler.fit(X_train_raw)

    X_train = scaler.transform(X_train_raw).astype(np.float32)
    X_val = scaler.transform(X_val_raw).astype(np.float32)

    X_train_3d = X_train.reshape(len(X_train), X_train.shape[1], 1)
    X_val_3d = X_val.reshape(len(X_val), X_val.shape[1], 1)

    # Track 1: contaminated vs normal
    model_track1 = _train_binary_model(
        X_train_3d,
        y_track1_all[train_idx],
        X_val_3d,
        y_track1_all[val_idx],
        gamma=2.0,
        alpha=0.33,
        seed=int(args.seed),
        epochs=int(args.epochs),
        batch_size=int(args.batch_size),
    )

    # Track 2: chem vs bio (trained only on contaminated batches)
    contaminated_mask = y_track1_all == 1
    contaminated_indices = np.where(contaminated_mask)[0]
    rng.shuffle(contaminated_indices)
    val2_size = max(1, int(len(contaminated_indices) * float(args.val_split)))
    val2_idx = contaminated_indices[:val2_size]
    train2_idx = contaminated_indices[val2_size:]

    X2_train = scaler.transform(X_all[train2_idx]).astype(np.float32).reshape(len(train2_idx), X_all.shape[1], 1)
    X2_val = scaler.transform(X_all[val2_idx]).astype(np.float32).reshape(len(val2_idx), X_all.shape[1], 1)

    # Build y2 aligned to contaminated indices order.
    contamination_by_batch = (
        df.assign(contamination=df["contamination"].astype(str).str.strip().str.lower())
        .groupby("batch_id")["contamination"]
        .agg(lambda s: s.value_counts().idxmax())
        .sort_index()
    )
    contaminated_batch_ids = contamination_by_batch[contamination_by_batch != "no"].index.to_numpy(dtype=int)
    y2_by_contaminated_order = contamination_by_batch.loc[contaminated_batch_ids].map({"bio": 0, "chem": 1}).astype(int).to_numpy()
    # Map from global batch index to y2 by contaminated order.
    batch_ids_sorted = np.sort(df["batch_id"].dropna().astype(int).unique())
    batch_id_to_index = {int(bid): int(i) for i, bid in enumerate(batch_ids_sorted)}
    contaminated_global_indices = np.array([batch_id_to_index[int(bid)] for bid in contaminated_batch_ids], dtype=int)
    global_to_y2 = {int(gidx): int(y2) for gidx, y2 in zip(contaminated_global_indices, y2_by_contaminated_order, strict=False)}
    y2_train = np.array([global_to_y2[int(i)] for i in train2_idx], dtype=np.int32)
    y2_val = np.array([global_to_y2[int(i)] for i in val2_idx], dtype=np.int32)

    model_track2 = _train_binary_model(
        X2_train,
        y2_train,
        X2_val,
        y2_val,
        gamma=3.0,
        alpha=0.5,
        seed=int(args.seed) + 7,
        epochs=int(args.epochs),
        batch_size=int(args.batch_size),
    )

    scaler_path = output_dir / "robust_scaler.pkl"
    track1_path = output_dir / "track1_inception_fold5.keras"
    track2_path = output_dir / "track2_inception_fold5.keras"
    meta_path = output_dir / "sensor_model_meta.json"

    joblib.dump(scaler, scaler_path)
    model_track1.save(track1_path)
    model_track2.save(track2_path)

    meta = {
        "csv_path": str(csv_path),
        "feature_columns": feature_cols,
        "feature_count": int(len(feature_cols)),
        "track1_target": "contaminated vs normal",
        "track2_target": "chem(1) vs bio(0) (contaminated only)",
        "tensorflow_visible_devices": os.getenv("CUDA_VISIBLE_DEVICES", ""),
    }
    import json

    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"[OK] Saved scaler: {scaler_path}")
    print(f"[OK] Saved track1 model: {track1_path}")
    print(f"[OK] Saved track2 model: {track2_path}")
    print(f"[OK] Saved meta: {meta_path}")


if __name__ == "__main__":
    main()
