import os
import re
import math
from hashlib import md5
from datetime import timedelta
from functools import lru_cache

import pandas as pd
import plotly.graph_objects as go
from dash import dcc, html
import numpy as np

from .heating_risk import HEATING_CAUTION_Z_ABS, HEATING_DANGER_Z_ABS, HEATING_WARNING_Z_ABS
from .final_product_risk import classify_final_product_batch

try:
    from .main_helpers import (
        CHECKPOINT_COUNT,
        CONTAMINATION_LABELS,
        LINE_COUNT,
        LOTS_PER_DAY_PER_LINE,
        OPERATION_DAYS,
        STATE_LABELS,
        STATE_ORDER,
        SNAPSHOT_RATIOS,
        build_kpi_items,
        build_danger_warning_masks,
        count_rows_by_threshold,
        get_runtime_env_value,
        load_process_batch_dataframe,
        normalize_contamination_value,
        resolve_process_csv_path,
    )
except ImportError:
    from main_helpers import (
        CHECKPOINT_COUNT,
        CONTAMINATION_LABELS,
        LINE_COUNT,
        LOTS_PER_DAY_PER_LINE,
        OPERATION_DAYS,
        STATE_LABELS,
        STATE_ORDER,
        SNAPSHOT_RATIOS,
        build_kpi_items,
        build_danger_warning_masks,
        count_rows_by_threshold,
        get_runtime_env_value,
        load_process_batch_dataframe,
        normalize_contamination_value,
        resolve_process_csv_path,
    )

TARGET_HOLD_TEMP = 72.0
TARGET_HOLD_RANGE = (71.5, 72.5)
TARGET_COOL_MAX = 7.0
STATE_COLORS = {
    "Receiving": "rgba(148, 163, 184, 0.10)",
    "Storage": "rgba(59, 130, 246, 0.08)",
    "Filter": "rgba(14, 165, 233, 0.08)",
    "Standardize": "rgba(99, 102, 241, 0.08)",
    "Heat": "rgba(249, 115, 22, 0.10)",
    "Hold": "rgba(34, 197, 94, 0.10)",
    "Cool": "rgba(6, 182, 212, 0.10)",
    "Fill": "rgba(59, 130, 246, 0.08)",
    "Inspect": "rgba(245, 158, 11, 0.10)",
    "Release": "rgba(168, 85, 247, 0.08)",
}
CONTAMINATION_BADGE = {"no": "정상", "chem": "경고", "bio": "위험"}
CONTAMINATION_SCORE = {"no": 1, "chem": 4, "bio": 5}
FINAL_INSPECTION_FOLDER_MAP = {
    "pure_milk": {"contamination": "no", "status": "PASS", "risk_level": "정상"},
    "water_mixed": {"contamination": "chem", "status": "조치요망", "risk_level": "경고"},
    "glucose_mixed": {"contamination": "bio", "status": "조치요망", "risk_level": "위험"},
}
FINAL_INSPECTION_FOLDER_ORDER = ["pure_milk", "water_mixed", "glucose_mixed"]
FINAL_INSPECTION_DAY_SPAN = OPERATION_DAYS
FINAL_INSPECTION_DAY_SAMPLE_SIZE = 1200
FINAL_INSPECTION_ACTIVE_BATCH_COUNT = 3
FINAL_INSPECTION_CHECKPOINT_COUNT = 10
from haccp_dashboard.lib.main_helpers import resolve_image_dataset_dir

FINAL_INSPECTION_DEFAULT_DATASET_DIR = resolve_image_dataset_dir()
RECENT_OPERATION_DAY_SPAN = 5


def get_configured_runs_per_day() -> int:
    # Backward-compatible helper (기존 코드의 runs/day 표현은 "일일 2시간 로트 수"를 의미).
    return int(LOTS_PER_DAY_PER_LINE)


def get_configured_line_count() -> int:
    # Backward-compatible helper (항상 3개 라인).
    return int(LINE_COUNT)


def _csv_path():
    return resolve_process_csv_path(os.path.dirname(__file__))


@lru_cache(maxsize=1)
def _load_process_dataframe() -> pd.DataFrame:
    # Updated loader: df_noisy.csv -> batch_150_contaminated_onlylabel_final_v4.csv with schema normalization.
    frame = load_process_batch_dataframe(_csv_path())
    try:
        from haccp_dashboard.lib.main_helpers import get_dashboard_now

        now = get_dashboard_now()
        if "datetime" in frame.columns:
            frame = frame[frame["datetime"] <= now].copy()
    except Exception:
        pass
    return frame


def _state_segments(batch_frame: pd.DataFrame):
    segments = []
    start_index = 0
    states = batch_frame["state"].tolist()
    datetimes = batch_frame["datetime"].tolist()
    for index in range(1, len(batch_frame)):
        if states[index] != states[start_index]:
            segments.append((states[start_index], datetimes[start_index], datetimes[index - 1]))
            start_index = index
    segments.append((states[start_index], datetimes[start_index], datetimes[-1]))
    return segments


def _resolve_contamination(series: pd.Series) -> str:
    normalized = series.dropna().map(normalize_contamination_value)
    if normalized.eq("bio").any():
        return "bio"
    if normalized.eq("chem").any():
        return "chem"
    return "no"


def _hold_minutes(batch_frame: pd.DataFrame) -> float:
    hold_slice = batch_frame[batch_frame["state"] == "Hold"]
    if hold_slice.empty:
        return 0.0
    return (hold_slice["datetime"].iloc[-1] - hold_slice["datetime"].iloc[0]).total_seconds() / 60.0


def _max_abs(series: pd.Series) -> float:
    return float(series.abs().max()) if not series.empty else 0.0


@lru_cache(maxsize=1)
def get_batch_summary_frame() -> pd.DataFrame:
    frame = _load_process_dataframe()
    records = []

    for batch_id, batch_frame in frame.groupby("batch_id", sort=True):
        batch_frame = batch_frame.sort_values("datetime").reset_index(drop=True)
        last_row = batch_frame.iloc[-1]
        peak_temp = float(batch_frame["T"].max())
        final_temp = float(last_row["T"])
        final_ph = float(last_row["pH"])
        contamination = _resolve_contamination(batch_frame["contamination"])
        hold_time_ok = bool(batch_frame["ccp_hold_time_ok"].min())
        hold_temp_ok = bool(batch_frame["ccp_hold_temp_ok"].min())
        hold_minutes = _hold_minutes(batch_frame)
        max_abs_t_z = _max_abs(batch_frame["T_z"].dropna())
        max_abs_ph_z = _max_abs(batch_frame["pH_z"].dropna())
        max_abs_mu_z = _max_abs(batch_frame["Mu_z"].dropna())
        max_abs_tau_z = _max_abs(batch_frame["Tau_z"].dropna())
        max_abs_z = max(max_abs_t_z, max_abs_ph_z, max_abs_mu_z, max_abs_tau_z)
        mean_abs_z = float(batch_frame[["T_z", "pH_z", "Mu_z", "Tau_z"]].abs().mean().mean())
        from haccp_dashboard.lib.main_helpers import build_danger_warning_masks

        danger_mask, warning_mask = build_danger_warning_masks(batch_frame)
        danger_count = int(danger_mask.sum())
        warning_count = int(warning_mask.sum())

        stability_score = max(0.0, min(100.0, 100.0 - (mean_abs_z * 18.0)))

        # 살균공정 3단계 위험도 판정 (주의 단계는 정상으로 통합)
        # 위험: 핵심 CCP 이탈 (온도 또는 유지시간)
        # 경고: 안정도 < 60% (물성 전반 지속 이탈)
        # 정상: 안정도 ≥ 60%
        if not hold_time_ok or not hold_temp_ok:
            risk_level = "위험"
        elif stability_score < 60.0:
            risk_level = "경고"
        else:
            risk_level = "정상"

        # 위험이 아닌 경우 PASS로 처리
        is_pass = risk_level in ("정상",)

        records.append(
            {
                "batch_id": int(batch_id),
                # 배치명은 라인별로 고유해야 하므로 batch_id 기준으로 유지한다.
                # (현재 로트/운영시점 정보는 별도 컬럼(line_run/line_day)로 표시)
                "batch_name": f"BATCH-{int(batch_id):03d}",
                "report_id": f"ST-IKS-{int(batch_id):04d}",
                "date": batch_frame["date"].iloc[0],
                "start_time": batch_frame["datetime"].iloc[0],
                "end_time": last_row["datetime"],
                "last_state": last_row["state"],
                "line_id": int(last_row["line_id"]) if "line_id" in batch_frame.columns and pd.notna(last_row.get("line_id")) else None,
                "line_run": int(last_row["line_run"]) if "line_run" in batch_frame.columns and pd.notna(last_row.get("line_run")) else None,
                "line_day": int(last_row["line_day"]) if "line_day" in batch_frame.columns and pd.notna(last_row.get("line_day")) else None,
                "peak_temp": peak_temp,
                "final_temp": final_temp,
                "final_ph": final_ph,
                "hold_minutes": hold_minutes,
                "contamination": contamination,
                "contamination_label": CONTAMINATION_LABELS.get(contamination, contamination),
                "contamination_badge": CONTAMINATION_BADGE[contamination],
                "hold_time_ok": hold_time_ok,
                "hold_temp_ok": hold_temp_ok,
                "max_abs_t_z": max_abs_t_z,
                "max_abs_ph_z": max_abs_ph_z,
                "max_abs_mu_z": max_abs_mu_z,
                "max_abs_tau_z": max_abs_tau_z,
                "max_abs_z": max_abs_z,
                "stability_score": stability_score,
                "status": "PASS" if is_pass else "조치요망",
                "risk_level": risk_level,
                "q_in_total": float(batch_frame["Q_in"].fillna(0).sum()),
                "q_out_total": float(batch_frame["Q_out"].fillna(0).sum()),
            }
        )

    return pd.DataFrame(records).sort_values(["date", "batch_id"], ascending=[False, False]).reset_index(drop=True)


def _triangular_score(series: pd.Series, target: float, tolerance: float) -> pd.Series:
    if tolerance <= 0:
        return pd.Series(0.0, index=series.index)
    return (1.0 - (series.sub(target).abs() / tolerance)).clip(lower=0.0, upper=1.0)


def _inside_band_score(series: pd.Series, lower: float, upper: float, margin: float) -> pd.Series:
    if margin <= 0:
        return pd.Series(0.0, index=series.index)

    nearest_edge = pd.concat([(series - lower).abs(), (series - upper).abs()], axis=1).min(axis=1)
    inside_score = (1.0 - (nearest_edge / margin)).clip(lower=0.0, upper=1.0)
    overshoot = (lower - series).clip(lower=0.0) + (series - upper).clip(lower=0.0)
    overshoot_penalty = (1.0 - (overshoot / margin)).clip(lower=0.0, upper=1.0)
    return (inside_score * overshoot_penalty).clip(lower=0.0, upper=1.0)


@lru_cache(maxsize=1)
def get_hidden_anomaly_batch_frame() -> pd.DataFrame:
    # 최근 운전(5일 x 10회) 가정에 맞춰 "week" 범위에서 이상 배치를 뽑습니다.
    summary = _filter_summary("week").copy()
    if summary.empty:
        return summary

    scored = summary.copy()
    scored["date"] = pd.to_datetime(scored["date"])

    scored["volatility_score"] = (
        scored["max_abs_z"].clip(upper=12).fillna(0) * 4.0
        + scored["max_abs_mu_z"].clip(upper=8).fillna(0) * 1.6
        + scored["max_abs_tau_z"].clip(upper=8).fillna(0) * 1.4
        + (100.0 - scored["stability_score"].fillna(100.0)).clip(lower=0) * 0.18
        + scored["peak_temp"].sub(64.0).abs().fillna(0) * 1.8
        + scored["final_temp"].sub(TARGET_COOL_MAX).clip(lower=0).fillna(0) * 3.2
        + (~scored["hold_time_ok"].fillna(True)).astype(int) * 8.0
        + (~scored["hold_temp_ok"].fillna(True)).astype(int) * 8.0
    )

    ranked = scored.sort_values(["volatility_score", "date", "batch_id"], ascending=[False, False, False]).reset_index(drop=True)
    ranked["line_index"] = ranked.index + 1
    return ranked


def get_hidden_anomaly_batch_items(limit: int = 3) -> list[dict]:
    ranked = get_hidden_anomaly_batch_frame().head(max(limit, 0)).copy()
    items = []
    for row in ranked.itertuples(index=False):
        items.append(
            {
                "batch_id": int(row.batch_id),
                "batch_name": row.batch_name,
                "date": str(pd.Timestamp(row.date).date()),
                "contamination": row.contamination,
                "contamination_label": row.contamination_label,
                "status": row.status,
                "stability_score": float(row.stability_score),
                "line_index": int(row.line_index),
                "chip_label": f"변동성 배치 {int(row.line_index)}",
                "hidden_anomaly_score": float(row.volatility_score),
                "volatility_score": float(row.volatility_score),
            }
        )
    return items


def get_hidden_anomaly_batch_ids(limit: int = 3) -> list[int]:
    return [int(item["batch_id"]) for item in get_hidden_anomaly_batch_items(limit=limit)]


def _filter_summary(period: str) -> pd.DataFrame:
    summary = get_batch_summary_frame()
    latest_date = summary["date"].max()
    per_day_target = get_configured_runs_per_day() * get_configured_line_count()

    if period == "today":
        filtered = summary[summary["date"] == latest_date].copy()
        # 데모 가정(라인 x 일일 운전횟수)에 맞게 day당 배치 수를 제한
        if not filtered.empty:
            filtered = filtered.sort_values(["date", "batch_id"], ascending=[False, False]).head(per_day_target)
        return filtered
    if period == "week":
        # 최근 5일(기본)만 사용
        min_date = latest_date - timedelta(days=RECENT_OPERATION_DAY_SPAN - 1)
        filtered = summary[summary["date"] >= min_date].copy()
        if filtered.empty:
            return filtered

        # 날짜별 (라인 x 일일 운전횟수) 가정에 맞춰 day당 배치 수를 제한
        rows = []
        for day in sorted(filtered["date"].unique(), reverse=True):
            day_slice = filtered[filtered["date"] == day].sort_values(["batch_id"], ascending=[False]).head(per_day_target)
            rows.append(day_slice)
        return pd.concat(rows, ignore_index=True) if rows else filtered.head(0)
    return summary.copy()


def _resolve_final_inspection_dataset_dir() -> str | None:
    candidates = [
        os.getenv("FINAL_INSPECTION_DATASET_DIR", "").strip(),
        FINAL_INSPECTION_DEFAULT_DATASET_DIR,
    ]

    for candidate in candidates:
        if not candidate:
            continue
        if os.path.isdir(candidate):
            return os.path.abspath(candidate)
    return None


def _deterministic_ratio(seed_text: str) -> float:
    digest = md5(seed_text.encode("utf-8")).hexdigest()
    return int(digest[:8], 16) / 0xFFFFFFFF


def _sample_group_id(file_name: str) -> str:
    return re.sub(r"_frame_\d+\.png$", "", file_name, flags=re.IGNORECASE)


def _normalize_ratio_map(score_map: dict[str, float]) -> dict[str, float]:
    # Allow very small probabilities (final inspection anomalies should be rare).
    sanitized = {key: max(float(value), 1e-6) for key, value in score_map.items()}
    total = sum(sanitized.values()) or 1.0
    return {key: value / total for key, value in sanitized.items()}


def _allocate_integer_counts(total: int, weight_map: dict[str, float]) -> dict[str, int]:
    if total <= 0:
        return {key: 0 for key in weight_map}

    normalized = _normalize_ratio_map(weight_map)
    raw = {key: normalized[key] * total for key in normalized}
    counts = {key: int(value) for key, value in raw.items()}
    remainder = total - sum(counts.values())
    ranked_keys = sorted(normalized.keys(), key=lambda key: (raw[key] - counts[key], key), reverse=True)

    for key in ranked_keys[:remainder]:
        counts[key] += 1
    return counts


def _score_process_batch_risk(row) -> float:
    return float(
        min(float(getattr(row, "max_abs_z", 0.0) or 0.0), 12.0) * 4.0
        + min(float(getattr(row, "max_abs_mu_z", 0.0) or 0.0), 8.0) * 1.6
        + min(float(getattr(row, "max_abs_tau_z", 0.0) or 0.0), 8.0) * 1.4
        + max(100.0 - float(getattr(row, "stability_score", 100.0) or 100.0), 0.0) * 0.18
        + abs(float(getattr(row, "peak_temp", TARGET_HOLD_TEMP) or TARGET_HOLD_TEMP) - TARGET_HOLD_TEMP) * 1.8
        + max(float(getattr(row, "final_temp", 0.0) or 0.0) - TARGET_COOL_MAX, 0.0) * 3.2
        + (0.0 if bool(getattr(row, "hold_time_ok", True)) else 8.0)
        + (0.0 if bool(getattr(row, "hold_temp_ok", True)) else 8.0)
    )


def _get_sensor_mix_metrics(frame: pd.DataFrame) -> dict:
    normal_count, warning_count, danger_count = count_rows_by_threshold(frame)
    counts = [int(normal_count), int(warning_count), int(danger_count)]
    total_count = sum(counts)
    active_state_count = sum(value > 0 for value in counts)
    if total_count <= 0:
        return {
            "normal_count": 0,
            "warning_count": 0,
            "danger_count": 0,
            "total_count": 0,
            "active_state_count": 0,
            "mix_score": 0.0,
        }

    expected = total_count / 3.0
    balance_penalty = sum(abs(value - expected) for value in counts)
    entropy = 0.0
    for value in counts:
        if value <= 0:
            continue
        ratio = float(value) / float(total_count)
        entropy -= ratio * math.log(ratio)

    mix_score = (active_state_count * 1000.0) + (entropy * 100.0) - balance_penalty
    return {
        "normal_count": int(normal_count),
        "warning_count": int(warning_count),
        "danger_count": int(danger_count),
        "total_count": int(total_count),
        "active_state_count": int(active_state_count),
        "mix_score": float(mix_score),
    }


def _map_risk_level_to_status_key(value) -> str:
    if str(value).strip() == "위험":
        return "danger"
    if str(value).strip() == "경고":
        return "warning"
    return "normal"


def _pick_final_inspection_batch_ids(process_summary: pd.DataFrame, day_date, limit: int = FINAL_INSPECTION_ACTIVE_BATCH_COUNT) -> list[int]:
    day_batches = process_summary[process_summary["date"] == day_date].copy()
    if day_batches.empty:
        return []

    ranked = day_batches.copy()
    ranked["risk_score"] = [
        _score_process_batch_risk(row)
        for row in ranked.itertuples(index=False)
    ]
    ranked = ranked.sort_values(["risk_score", "batch_id"], ascending=[False, False]).reset_index(drop=True)
    return [int(row.batch_id) for row in ranked.head(max(int(limit), 0)).itertuples(index=False)]


def _pick_sensor_mixed_main_batch_ids_with_fallback(
    process_summary: pd.DataFrame,
    target_day_date,
    candidate_dates: list,
    limit: int = 3,
) -> list[int]:
    limit = max(int(limit), 0)
    if limit <= 0:
        return []

    ranked_summary = process_summary.copy()
    if ranked_summary.empty:
        return []

    process_frame = _load_process_dataframe().copy()
    process_frame["date"] = pd.to_datetime(process_frame["date"]).dt.date
    process_frame = process_frame[process_frame["date"].isin(candidate_dates)].copy()
    if process_frame.empty:
        return []

    batch_records = []
    for (day_date, batch_id), batch_frame in process_frame.groupby(["date", "batch_id"]):
        mix_metrics = _get_sensor_mix_metrics(batch_frame)
        batch_records.append(
            {
                "date": day_date,
                "batch_id": int(batch_id),
                "target_date_priority": 1 if day_date == target_day_date else 0,
                "active_state_count": mix_metrics["active_state_count"],
                "mix_score": mix_metrics["mix_score"],
                "normal_count": mix_metrics["normal_count"],
                "warning_count": mix_metrics["warning_count"],
                "danger_count": mix_metrics["danger_count"],
            }
        )

    ranked = pd.DataFrame(batch_records)
    if ranked.empty:
        return []

    ranked = ranked.sort_values(
        ["active_state_count", "target_date_priority", "mix_score", "date", "batch_id"],
        ascending=[False, False, False, False, False],
    ).reset_index(drop=True)
    return [int(value) for value in ranked["batch_id"].head(limit).tolist()]


@lru_cache(maxsize=1)
def get_final_inspection_dataset_profile() -> dict:
    dataset_dir = _resolve_final_inspection_dataset_dir()
    contamination_counts = {"no": 0, "chem": 0, "bio": 0}
    folder_counts = {folder_name: 0 for folder_name in FINAL_INSPECTION_FOLDER_ORDER}

    if dataset_dir and os.path.isdir(dataset_dir):
        for folder_name in FINAL_INSPECTION_FOLDER_ORDER:
            folder_path = os.path.join(dataset_dir, folder_name)
            if not os.path.isdir(folder_path):
                continue

            file_count = 0
            for _root, _dirs, files in os.walk(folder_path):
                for file_name in files:
                    if os.path.splitext(file_name)[1].lower() in {".png", ".jpg", ".jpeg", ".webp"}:
                        file_count += 1

            folder_counts[folder_name] = file_count
            contamination = FINAL_INSPECTION_FOLDER_MAP[folder_name]["contamination"]
            contamination_counts[contamination] += file_count

    total_images = int(sum(contamination_counts.values()))
    expected_total = FINAL_INSPECTION_DAY_SPAN * FINAL_INSPECTION_DAY_SAMPLE_SIZE
    per_day_sample_size = FINAL_INSPECTION_DAY_SAMPLE_SIZE
    if FINAL_INSPECTION_DAY_SPAN > 0 and total_images >= FINAL_INSPECTION_DAY_SPAN:
        per_day_sample_size = max(total_images // FINAL_INSPECTION_DAY_SPAN, 1)

    # NOTE:
    # - `contamination_weights` reflects the dataset folder balance (pure/water/glucose).
    # - Real factory QA/QC distribution MUST NOT follow a perfectly balanced dataset.
    #   Operationally, "정상" 비율이 압도적으로 높고, "의심/부적합"은 드물게 발생합니다.
    if total_images <= 0:
        contamination_weights = {"no": 1 / 3, "chem": 1 / 3, "bio": 1 / 3}
    else:
        contamination_weights = {key: float(value) / float(total_images) for key, value in contamination_counts.items()}

    # Default operational mix (per-image probability) used for batch-level final inspection simulation.
    # Target behavior:
    # - 대부분 적합(PASS)
    # - 일부 보류(경고)
    # - 드물게 불합격(위험)
    operational_weights = {"no": 0.965, "chem": 0.025, "bio": 0.010}

    return {
        "dataset_dir": dataset_dir,
        "folder_counts": folder_counts,
        "contamination_counts": contamination_counts,
        "total_images": total_images,
        "expected_total": expected_total,
        "matches_expected_total": total_images == expected_total,
        "per_day_sample_size": per_day_sample_size,
        "contamination_weights": contamination_weights,
        "operational_weights": operational_weights,
    }


def _sample_daily_inspection_mix(day_date, base_weights: dict[str, float] | None = None) -> dict[str, float]:
    seed = str(day_date)
    base = base_weights or {"no": 1 / 3, "chem": 1 / 3, "bio": 1 / 3}
    return _normalize_ratio_map(
        {
            # Small day-to-day drift (keep operational realism: anomalies remain rare).
            "no": max(base.get("no", 0.98) + ((_deterministic_ratio(f"{seed}:pure") - 0.5) * 0.015), 0.60),
            "chem": max(base.get("chem", 0.01) + ((_deterministic_ratio(f"{seed}:chem") - 0.5) * 0.010), 0.001),
            "bio": max(base.get("bio", 0.005) + ((_deterministic_ratio(f"{seed}:bio") - 0.5) * 0.005), 0.001),
        }
    )


def _sample_checkpoint_inspection_mix(day_date, batch_id: int, checkpoint: int, base_mix: dict[str, float]) -> dict[str, float]:
    seed = f"{day_date}:{int(batch_id)}:{int(checkpoint)}"
    return _normalize_ratio_map(
        {
            # Keep checkpoint variation subtle; operationally the mix does not swing wildly per 2h-lot.
            "no": base_mix["no"] + ((_deterministic_ratio(f"{seed}:no") - 0.5) * 0.008),
            "chem": base_mix["chem"] + ((_deterministic_ratio(f"{seed}:chem") - 0.5) * 0.006),
            "bio": base_mix["bio"] + ((_deterministic_ratio(f"{seed}:bio") - 0.5) * 0.004),
        }
    )


def _apply_final_inspection_date_filter(frame: pd.DataFrame, target_date: str | None = None) -> pd.DataFrame:
    if frame.empty or not target_date:
        return frame.copy()

    resolved = pd.to_datetime(target_date, errors="coerce")
    if pd.isna(resolved):
        return frame.copy()

    resolved_date = resolved.date()
    dated = frame.copy()
    dated["date"] = pd.to_datetime(dated["date"]).dt.date
    return dated[dated["date"] == resolved_date].copy()


def _empty_final_inspection_frame() -> pd.DataFrame:
    return pd.DataFrame(
        columns=[
            "batch_id",
            "batch_name",
            "report_id",
            "date",
            "start_time",
            "end_time",
            "last_state",
            "peak_temp",
            "final_temp",
            "final_ph",
            "hold_minutes",
            "checkpoint",
            "line_id",
            "line_run",
            "line_day",
            "contamination",
            "contamination_label",
            "contamination_badge",
            "hold_time_ok",
            "hold_temp_ok",
            "max_abs_t_z",
            "max_abs_ph_z",
            "max_abs_mu_z",
            "max_abs_tau_z",
            "max_abs_z",
            "stability_score",
            "status",
            "risk_level",
            "q_in_total",
            "q_out_total",
            "sensor_contamination",
        ]
    )


def _build_final_inspection_dataset_frame(dataset_dir: str | None = None) -> pd.DataFrame:
    """
    최종검사 이미지를 파일 단위로 재현하지 않고,
    실데이터 총량을 기준으로 날짜별 샘플을 리스크 상위 운영 배치 3개 × 일일 2시간 로트 순번 10개에 맞춰 결정적으로 분배합니다.

    운영 구조 가정(요구사항 기반):
    - 5일 운영, 기본 기준은 하루 1200장(총 6000장)이며 실제 이미지 총량으로 검증
    - 표시용 운영 배치: 날짜당 리스크 상위 대표 배치 3개
    - 배치당 이미지 400장(=1200/3)
    - 라인 기준 하루 20시간 가동(2시간 로트 10개)을 기본 가정으로 사용
    - 날짜별 우유/우유+물/우유+물+포도당 비율은 실데이터 분포를 바탕으로 결정적 변동
    """
    del dataset_dir
    process_summary = get_batch_summary_frame()
    if process_summary.empty:
        return _empty_final_inspection_frame()

    process_summary = process_summary.copy()
    process_summary["date"] = pd.to_datetime(process_summary["date"]).dt.date
    available_dates = sorted(process_summary["date"].unique())
    if not available_dates:
        return _empty_final_inspection_frame()

    # 최근 5일만 사용(기본)
    available_dates = available_dates[-FINAL_INSPECTION_DAY_SPAN:]

    dataset_profile = get_final_inspection_dataset_profile()
    per_day_sample_size = int(dataset_profile.get("per_day_sample_size") or FINAL_INSPECTION_DAY_SAMPLE_SIZE)
    # Use operational mix (factory-like) instead of dataset balance.
    contamination_weights = dict(dataset_profile.get("operational_weights") or {})

    # 센서 요약 lookup
    sensor_lookup = {}
    for row in process_summary.itertuples(index=False):
        try:
            sensor_lookup[int(row.batch_id)] = row
        except Exception:
            continue

    sample_records = []
    report_seq = 0
    run_count = get_configured_runs_per_day()

    for day_date in available_dates:
        day_batches = process_summary[process_summary["date"] == day_date].copy()
        if not day_batches.empty:
            day_batches = day_batches.sort_values(["line_id", "line_run", "batch_id"], ascending=[True, True, True])
        batch_ids = [int(value) for value in day_batches["batch_id"].dropna().astype(int).tolist()]
        if not batch_ids:
            continue

        base_mix = _sample_daily_inspection_mix(day_date, contamination_weights)

        # Allocate per-batch image sample counts with mild randomness (avoid excessive skew).
        batch_weight_map = {}
        for batch_id in batch_ids:
            jitter = ((_deterministic_ratio(f"{day_date}:{int(batch_id)}:batch_total") - 0.5) * 0.25)
            batch_weight_map[str(batch_id)] = max(1.0 + jitter, 0.7)

        day_batch_counts = _allocate_integer_counts(per_day_sample_size, batch_weight_map)

        for batch_order, batch_id in enumerate(batch_ids, start=1):
            batch_total = int(day_batch_counts.get(str(batch_id), 0))
            if batch_total <= 0:
                continue

            sensor_row = sensor_lookup.get(batch_id)
            if sensor_row is not None:
                peak_temp = float(getattr(sensor_row, "peak_temp", 0.0))
                final_temp = float(getattr(sensor_row, "final_temp", 0.0))
                final_ph = float(getattr(sensor_row, "final_ph", 0.0))
                hold_minutes = float(getattr(sensor_row, "hold_minutes", 0.0))
                hold_time_ok = bool(getattr(sensor_row, "hold_time_ok", True))
                hold_temp_ok = bool(getattr(sensor_row, "hold_temp_ok", True))
                stability_score = float(getattr(sensor_row, "stability_score", 0.0))
                last_state = str(getattr(sensor_row, "last_state", ""))
                start_time = getattr(sensor_row, "start_time", pd.Timestamp(day_date))
                end_time = getattr(sensor_row, "end_time", pd.Timestamp(day_date))
                max_abs_t_z = float(getattr(sensor_row, "max_abs_t_z", 0.0))
                max_abs_ph_z = float(getattr(sensor_row, "max_abs_ph_z", 0.0))
                max_abs_mu_z = float(getattr(sensor_row, "max_abs_mu_z", 0.0))
                max_abs_tau_z = float(getattr(sensor_row, "max_abs_tau_z", 0.0))
                max_abs_z = float(getattr(sensor_row, "max_abs_z", 0.0))
                sensor_contamination = str(getattr(sensor_row, "contamination", "no"))
                line_id = int(getattr(sensor_row, "line_id", batch_order) or batch_order)
                line_day = int(getattr(sensor_row, "line_day", 1) or 1)
                line_run = int(getattr(sensor_row, "line_run", batch_order) or batch_order)
            else:
                peak_temp = 0.0
                final_temp = 0.0
                final_ph = 0.0
                hold_minutes = 0.0
                hold_time_ok = True
                hold_temp_ok = True
                stability_score = 0.0
                last_state = "Release"
                start_time = pd.Timestamp(day_date)
                end_time = pd.Timestamp(day_date)
                max_abs_t_z = 0.0
                max_abs_ph_z = 0.0
                max_abs_mu_z = 0.0
                max_abs_tau_z = 0.0
                max_abs_z = 0.0
                sensor_contamination = "no"
                line_id = batch_order
                line_day = 1
                line_run = batch_order

            line_run = max(1, min(int(line_run), run_count))
            run_mix = _sample_checkpoint_inspection_mix(day_date, batch_id, line_run, base_mix)

            # Correlate final inspection anomaly likelihood with sensor-side risk, but keep it modest.
            try:
                sensor_risk = str(getattr(sensor_row, "risk_level", "정상")) if sensor_row is not None else "정상"
            except Exception:
                sensor_risk = "정상"
            try:
                sensor_ccp_fail = (not bool(hold_time_ok)) or (not bool(hold_temp_ok))
            except Exception:
                sensor_ccp_fail = False

            adjusted = dict(run_mix)
            if sensor_ccp_fail:
                adjusted["chem"] = float(adjusted.get("chem", 0.0)) * 2.2
                adjusted["bio"] = float(adjusted.get("bio", 0.0)) * 4.0
            elif sensor_risk == "위험":
                adjusted["chem"] = float(adjusted.get("chem", 0.0)) * 1.8
                adjusted["bio"] = float(adjusted.get("bio", 0.0)) * 2.4
            elif sensor_risk == "경고":
                adjusted["chem"] = float(adjusted.get("chem", 0.0)) * 1.5
                adjusted["bio"] = float(adjusted.get("bio", 0.0)) * 1.2

            run_mix = _normalize_ratio_map(adjusted)

            # Random-but-stable allocation (deterministic seed) for realism:
            # rare anomalies should appear sometimes, not be rounded away deterministically.
            seed_text = f"{day_date}:{int(batch_id)}:{int(line_run)}:final_inspection_mix"
            seed_int = int(md5(seed_text.encode("utf-8")).hexdigest()[:8], 16)
            rng = np.random.default_rng(seed_int)
            probs = [float(run_mix.get("no", 0.0)), float(run_mix.get("chem", 0.0)), float(run_mix.get("bio", 0.0))]
            probs_sum = sum(probs) or 1.0
            probs = [p / probs_sum for p in probs]
            sampled = rng.multinomial(int(batch_total), probs)
            contamination_counts = {"no": int(sampled[0]), "chem": int(sampled[1]), "bio": int(sampled[2])}

            # Guardrails: avoid unrealistic concentration of anomalies within a single batch.
            chem_count = int(contamination_counts.get("chem", 0))
            bio_count = int(contamination_counts.get("bio", 0))
            no_count = int(contamination_counts.get("no", 0))

            # 실제 살균공정: bio 1건이라도 즉시 폐기 → 극히 드물게만 허용
            # chem(의심)도 1~2건 수준으로 억제
            max_bio = 1
            max_chem = 2 if sensor_risk in {"경고", "위험"} or sensor_ccp_fail else 1
            if bio_count > max_bio:
                no_count += (bio_count - max_bio)
                bio_count = max_bio
            if chem_count > max_chem:
                no_count += (chem_count - max_chem)
                chem_count = max_chem
            # bio와 chem이 동시에 있으면 chem 1건으로 제한 (현실: bio 발생 시 전량 폐기, 추가 분류 불필요)
            if bio_count >= 1 and chem_count >= 1:
                no_count += chem_count
                chem_count = 0

            contamination_counts = {"no": int(no_count), "chem": int(chem_count), "bio": int(bio_count)}

            for contamination in ["no", "chem", "bio"]:
                status = "PASS" if contamination == "no" else "조치요망"
                risk_level = "위험" if contamination == "bio" else "경고" if contamination == "chem" else "정상"
                for _ in range(int(contamination_counts.get(contamination, 0))):
                    report_seq += 1
                    sample_records.append(
                        {
                            "batch_id": batch_id,
                            # 배치명은 라인별로 고유해야 하므로 batch_id 기준으로 유지한다.
                            "batch_name": f"BATCH-{batch_id:03d}",
                            "report_id": f"FI-{day_date}-{batch_id:03d}-{report_seq:05d}",
                            "date": day_date,
                            "start_time": start_time,
                            "end_time": end_time,
                            "last_state": last_state or "Release",
                            "peak_temp": peak_temp,
                            "final_temp": final_temp,
                            "final_ph": final_ph,
                            "hold_minutes": hold_minutes,
                            "checkpoint": int(line_run),
                            "line_id": int(line_id),
                            "line_run": int(line_run),
                            "line_day": int(line_day),
                            "contamination": contamination,
                            "contamination_label": CONTAMINATION_LABELS.get(contamination, contamination),
                            "contamination_badge": CONTAMINATION_BADGE[contamination],
                            "hold_time_ok": hold_time_ok,
                            "hold_temp_ok": hold_temp_ok,
                            "max_abs_t_z": max_abs_t_z,
                            "max_abs_ph_z": max_abs_ph_z,
                            "max_abs_mu_z": max_abs_mu_z,
                            "max_abs_tau_z": max_abs_tau_z,
                            "max_abs_z": max_abs_z,
                            "stability_score": stability_score,
                            "status": status,
                            "risk_level": risk_level,
                            "q_in_total": 1.0,
                            "q_out_total": 1.0 if contamination == "no" else 0.0,
                            "sensor_contamination": sensor_contamination,
                        }
                    )

    if not sample_records:
        return _empty_final_inspection_frame()

    return pd.DataFrame(sample_records, columns=_empty_final_inspection_frame().columns)


@lru_cache(maxsize=1)
def get_final_inspection_summary_frame() -> pd.DataFrame:
    dataset_dir = _resolve_final_inspection_dataset_dir()
    summary = _build_final_inspection_dataset_frame(dataset_dir)

    # 시나리오: 현재 로트(예: 8)는 공정 진행 중이므로 최종검사 확정 기록에 포함하지 않는다.
    try:
        from haccp_dashboard.lib.main_helpers import get_dashboard_current_lot_index, get_dashboard_now

        now = get_dashboard_now()
        current_lot = int(get_dashboard_current_lot_index())
        summary = summary.copy()
        summary["date"] = pd.to_datetime(summary["date"]).dt.date
        summary = summary[summary["date"] == pd.Timestamp(now).date()]
        if "line_run" in summary.columns:
            summary = summary[pd.to_numeric(summary["line_run"], errors="coerce").fillna(0).astype(int) < current_lot]
    except Exception:
        pass

    return summary.sort_values(["date", "batch_id"], ascending=[False, False]).reset_index(drop=True)


@lru_cache(maxsize=1)
def get_final_product_batch_summary_frame() -> pd.DataFrame:
    """
    최종제품공정 배치 단위 출하판정 프레임.

    - 정상: 확정 부적합 0 & 의심 0  → 출하 가능
    - 경고: 확정 부적합 0 & 의심 ≥ 1 → 출하 보류(재검/추가확인)
    - 위험: 확정 부적합 ≥ 1        → 즉시 출하 보류

    NOTE(데모 매핑):
    - bio = 확정 부적합(confirmed nonconforming)
    - chem = 의심(suspect)
    """
    summary = get_final_inspection_summary_frame()
    if summary.empty:
        return pd.DataFrame(
            columns=[
                "date",
                "batch_id",
                "batch_name",
                "report_id",
                "final_ph",
                "final_temp",
                "sample_count",
                "suspect_count",
                "confirmed_nonconforming_count",
                "risk_level",
                "status",
                "disposition",
                "shipment_ok",
            ]
        )

    frame = summary.copy()
    frame["date"] = pd.to_datetime(frame["date"]).dt.date
    grouped = frame.groupby(["date", "batch_id"], as_index=False).agg(
        batch_name=("batch_name", "first"),
        report_id=("report_id", "first"),
        final_ph=("final_ph", "mean"),
        final_temp=("final_temp", "mean"),
        sample_count=("q_in_total", "sum"),
        suspect_count=("contamination", lambda s: int(pd.Series(s).eq("chem").sum())),
        confirmed_nonconforming_count=("contamination", lambda s: int(pd.Series(s).eq("bio").sum())),
    )

    decisions = grouped.apply(
        lambda row: classify_final_product_batch(
            confirmed_nonconforming_count=int(row["confirmed_nonconforming_count"]),
            suspect_count=int(row["suspect_count"]),
            sample_count=int(float(row["sample_count"])),
        ),
        axis=1,
    )
    grouped["risk_level"] = [d.level for d in decisions]
    grouped["shipment_ok"] = [bool(d.shipment_ok) for d in decisions]
    grouped["disposition"] = [d.disposition for d in decisions]
    grouped["status"] = grouped["disposition"].map(lambda v: "PASS" if v == "출하 가능" else v)

    return grouped.sort_values(["date", "batch_id"], ascending=[False, False]).reset_index(drop=True)


def _filter_final_inspection_summary(period: str) -> pd.DataFrame:
    summary = get_final_inspection_summary_frame()
    if summary.empty:
        return summary.copy()

    latest_date = summary["date"].max()
    if period == "today":
        return summary[summary["date"] == latest_date].copy()
    if period == "week":
        min_date = latest_date - timedelta(days=FINAL_INSPECTION_DAY_SPAN - 1)
        return summary[summary["date"] >= min_date].copy()
    return summary.copy()


def get_final_inspection_available_dates(period: str = "week") -> list[str]:
    filtered = _filter_final_inspection_summary(period)
    if filtered.empty:
        filtered = get_final_inspection_summary_frame()
    if filtered.empty:
        return []

    dates = sorted(pd.to_datetime(filtered["date"]).dt.date.unique(), reverse=True)
    return [str(day) for day in dates]


def get_main_operational_available_dates(period: str = "week") -> list[str]:
    filtered = _filter_summary(period)
    if filtered.empty:
        filtered = get_batch_summary_frame()
    if filtered.empty:
        return []

    dates = sorted(pd.to_datetime(filtered["date"]).dt.date.unique(), reverse=True)
    return [str(day) for day in dates]


def _resolve_main_operational_date(target_date: str | None = None, period: str = "today") -> str | None:
    available_dates = get_main_operational_available_dates(period)
    if not available_dates:
        return None
    if target_date in available_dates:
        return target_date
    return available_dates[0]


def get_main_final_inspection_batch_ids(limit: int = 3, period: str = "today", target_date: str | None = None) -> list[int]:
    target_date = _resolve_main_operational_date(target_date, period)
    if not target_date:
        return []

    process_summary = get_batch_summary_frame().copy()
    process_summary["date"] = pd.to_datetime(process_summary["date"]).dt.date
    candidate_dates = [pd.to_datetime(value).date() for value in get_main_operational_available_dates(period)]
    return _pick_sensor_mixed_main_batch_ids_with_fallback(
        process_summary,
        pd.to_datetime(target_date).date(),
        candidate_dates=candidate_dates,
        limit=max(int(limit), 0),
    )


def _get_main_operational_day_frame(target_date: str | None = None, period: str = "week") -> pd.DataFrame:
    resolved_date = _resolve_main_operational_date(target_date, period)
    process_frame = _load_process_dataframe().copy()
    if process_frame.empty or not resolved_date:
        return process_frame.head(0)

    process_frame["date"] = pd.to_datetime(process_frame["date"]).dt.date
    return process_frame[process_frame["date"] == pd.to_datetime(resolved_date).date()].copy()


def _classify_main_operational_status(batch_slice: pd.DataFrame, batch_frame: pd.DataFrame, checkpoint: int, checkpoint_total: int) -> str:
    if batch_slice.empty:
        return "normal"

    danger_mask, warning_mask = build_danger_warning_masks(batch_slice)

    # 공통 규칙(가열공정 센서 위험판정):
    # - 위험: CCP 플래그 이탈 또는 z-score(>=3.0) 정상범위 이탈
    # - 경고: 정상범위 내이지만 z-score(>=2.0) 변동성 증가
    # 위 기준은 `build_danger_warning_masks`/`heating_risk`에 의해 일관되게 계산됩니다.
    if bool(danger_mask.any()):
        return "danger"

    final_contamination_detected = False
    if checkpoint >= checkpoint_total and "contamination" in batch_frame.columns:
        final_contamination_detected = batch_frame["contamination"].map(normalize_contamination_value).ne("no").any()

    if bool(warning_mask.any()) or final_contamination_detected:
        return "warning"
    return "normal"


def get_main_operational_status_flow_frame(target_date: str | None = None, period: str = "week") -> pd.DataFrame:
    resolved_date = _resolve_main_operational_date(target_date, period)
    run_total = get_configured_runs_per_day()

    if not resolved_date:
        return pd.DataFrame(columns=["date", "run_number", "status_key", "status_label", "count", "batch_total"])

    process_summary = get_batch_summary_frame().copy()
    process_summary["date"] = pd.to_datetime(process_summary["date"]).dt.date
    process_summary = process_summary[process_summary["date"] == pd.to_datetime(resolved_date).date()].copy()
    if process_summary.empty:
        return pd.DataFrame(columns=["date", "run_number", "status_key", "status_label", "count", "batch_total"])

    process_summary["run_number"] = pd.to_numeric(process_summary.get("line_run", 1), errors="coerce").fillna(1).astype(int).clip(lower=1, upper=run_total)
    process_summary["risk_score"] = [
        _score_process_batch_risk(row)
        for row in process_summary.itertuples(index=False)
    ]
    process_summary["status_key"] = process_summary["risk_level"].map(_map_risk_level_to_status_key)
    records = []
    status_meta = {
        "normal": "정상",
        "warning": "경고",
        "danger": "위험",
    }
    for run_number in range(1, run_total + 1):
        run_slice = process_summary[process_summary["run_number"] == run_number].copy()
        batch_total = int(run_slice["batch_id"].nunique()) if not run_slice.empty else 0
        for status_key in ["normal", "warning", "danger"]:
            status_slice = run_slice[run_slice["status_key"] == status_key].copy()
            count = int(status_slice["batch_id"].nunique()) if not status_slice.empty else 0
            top_batches = []
            if not status_slice.empty:
                ranked = status_slice.sort_values(["risk_score", "batch_id"], ascending=[False, False])
                top_batches = ranked["batch_name"].head(2).astype(str).tolist()

            records.append(
                {
                    "date": resolved_date,
                    "run_number": run_number,
                    "status_key": status_key,
                    "status_label": status_meta[status_key],
                    "count": count,
                    "batch_total": batch_total,
                    "share_pct": (float(count) / float(batch_total) * 100.0) if batch_total else 0.0,
                    "top_batches": ", ".join(top_batches),
                }
            )

    return pd.DataFrame(records)


def build_main_operational_graph_footnote(target_date: str | None = None, period: str = "week"):
    target_date = _resolve_main_operational_date(target_date, period)
    flow_frame = get_main_operational_status_flow_frame(target_date, period)
    if flow_frame.empty:
        return html.Div("위험 증가 주요 원인: -", className="factory-graph-footnote")

    danger_rows = flow_frame[flow_frame["status_key"] == "danger"].sort_values(["count", "run_number"], ascending=[False, False])
    if danger_rows.empty or int(danger_rows.iloc[0]["count"]) <= 0:
        return html.Div("위험 집중 로트: 없음", className="factory-graph-footnote")

    peak = danger_rows.iloc[0]
    top_batches = str(peak["top_batches"]).strip() or "이상 배치 없음"
    return html.Div(f"위험 집중 로트 {int(peak['run_number'])}: {top_batches}", className="factory-graph-footnote")


def _get_main_operational_status_snapshot(target_date: str | None = None, period: str = "week") -> dict:
    resolved_date = _resolve_main_operational_date(target_date, period)
    day_frame = _get_main_operational_day_frame(resolved_date, period)
    flow_frame = get_main_operational_status_flow_frame(resolved_date, period)
    summary_frame = get_batch_summary_frame().copy()
    summary_frame["date"] = pd.to_datetime(summary_frame["date"]).dt.date
    summary_frame = summary_frame[summary_frame["date"] == pd.to_datetime(resolved_date).date()].copy()
    final_counts = {
        status_key: int(summary_frame[summary_frame["risk_level"].map(_map_risk_level_to_status_key) == status_key]["batch_id"].nunique())
        for status_key in ["normal", "warning", "danger"]
    }
    kpi_items = build_kpi_items(day_frame)

    return {
        "date": resolved_date,
        "batch_total": int(day_frame["batch_id"].nunique()) if not day_frame.empty and "batch_id" in day_frame.columns else 0,
        "normal_count": final_counts.get("normal", 0),
        "warning_count": final_counts.get("warning", 0),
        "danger_count": final_counts.get("danger", 0),
        "kpi_items": kpi_items,
        "flow_frame": flow_frame,
    }


def get_final_inspection_dataset_validation_message() -> str:
    profile = get_final_inspection_dataset_profile()
    total_images = int(profile.get("total_images") or 0)
    expected_total = int(profile.get("expected_total") or 0)
    per_day_sample_size = int(profile.get("per_day_sample_size") or 0)
    folder_counts = profile.get("folder_counts") or {}
    folder_summary = ", ".join(f"{folder} {int(count):,}장" for folder, count in folder_counts.items())

    if total_images <= 0:
        return "실제 이미지 수를 찾지 못해 기본 1200장 규칙으로 표시합니다."
    if total_images == expected_total:
        return f"실데이터 검증 완료: 총 {total_images:,}장으로 5일 x {per_day_sample_size:,}장 규칙과 일치합니다. ({folder_summary})"
    return f"실데이터 기준으로 전환: 총 {total_images:,}장이라 5일 x {per_day_sample_size:,}장 집계로 표시합니다. ({folder_summary})"


def get_batch_options(period: str = "week"):
    filtered = _filter_summary(period)
    if filtered.empty:
        filtered = get_batch_summary_frame()
    return [
        {"label": f"{row.batch_name} · {row.date}", "value": int(row.batch_id)}
        for row in filtered.sort_values(["date", "batch_id"], ascending=[False, False]).itertuples()
    ]


def get_default_batch_id() -> int:
    summary = get_batch_summary_frame()
    return int(summary.iloc[0]["batch_id"])


HEATING_SUMMARY_ORDER = ["no", "chem", "bio"]
HEATING_SUMMARY_META = {
    "no": {"group_label": "정상 대표 배치"},
    "chem": {"group_label": "화학 이상 대표 배치"},
    "bio": {"group_label": "미생물 이상 대표 배치"},
}


def get_heating_batch_summaries(period: str = "week"):
    filtered = _filter_summary(period)
    full_summary = get_batch_summary_frame()
    source = filtered if not filtered.empty else full_summary
    summary_rows = []

    for contamination in HEATING_SUMMARY_ORDER:
        candidates = source[source["contamination"] == contamination]
        if candidates.empty:
            candidates = full_summary[full_summary["contamination"] == contamination]
        if candidates.empty:
            continue

        row = candidates.sort_values(
            ["date", "stability_score", "batch_id"],
            ascending=[False, False, False],
        ).iloc[0]
        summary_rows.append(
            {
                "batch_id": int(row["batch_id"]),
                "batch_name": row["batch_name"],
                "date": str(row["date"]),
                "contamination": contamination,
                "contamination_label": row["contamination_label"],
                "status": row["status"],
                "stability_score": float(row["stability_score"]),
                "group_label": HEATING_SUMMARY_META[contamination]["group_label"],
            }
        )

    return summary_rows


def get_heating_batch_options(period: str = "week"):
    return [
        {
            "label": f"{item['group_label']} · {item['batch_name']} · {item['date']}",
            "value": int(item["batch_id"]),
        }
        for item in get_heating_batch_summaries(period)
    ]


def get_default_heating_batch_id(period: str = "week") -> int:
    summary_rows = get_heating_batch_summaries(period)
    if summary_rows:
        return int(summary_rows[0]["batch_id"])
    return get_default_batch_id()


def get_heating_overview() -> dict:
    today = _filter_summary("today")
    process_frame = _load_process_dataframe()
    if process_frame.empty:
        return {
            "current_batch_count": 0,
            "inspection_count": 0,
            "ccp_deviation_count": 0,
            "stability_score": "0.0%",
        }

    latest_date = process_frame["date"].max()
    today_process = process_frame[process_frame["date"] == latest_date].copy()
    latest_rows = today_process.sort_values("datetime").groupby("batch_id", sort=False).tail(1)
    active_batch_count = int(latest_rows["state"].ne("Release").sum())
    inspection_count = int(len(today_process))

    return {
        "current_batch_count": active_batch_count,
        "inspection_count": inspection_count,
        "ccp_deviation_count": int(today["status"].ne("PASS").sum()),
        "stability_score": f"{today['stability_score'].mean():.1f}%" if not today.empty else "0.0%",
    }


def get_report_rows(period: str):
    filtered = _filter_summary(period)
    rows = []
    for row in filtered.sort_values(["date", "batch_id"], ascending=[False, False]).itertuples():
        rows.append(
            {
                "batch_id": int(row.batch_id),
                "batch_name": row.batch_name,
                "line_id": int(row.line_id) if hasattr(row, "line_id") and row.line_id is not None else "-",
                "report_id": row.report_id,
                "date": str(row.date),
                "contamination_label": row.contamination_label,
                "contamination_badge": row.contamination_badge,
                "peak_temp": float(row.peak_temp),
                "deviation": float(row.peak_temp - TARGET_HOLD_TEMP),
                "hold_minutes": float(row.hold_minutes),
                "stability_score": float(row.stability_score),
                "status": row.status,
            }
        )
    return rows


def get_final_inspection_metrics(period: str, target_date: str | None = None):
    filtered = _apply_final_inspection_date_filter(_filter_final_inspection_summary(period), target_date)
    total_samples = len(filtered)
    pass_count = int(filtered["status"].eq("PASS").sum())
    contaminated = int(filtered["contamination"].ne("no").sum())
    clean_samples = total_samples - contaminated
    pass_rate = (pass_count / total_samples * 100.0) if total_samples else 0.0
    high_risk = int(filtered["risk_level"].eq("위험").sum())
    
    # 최종제품검사용 메트릭: 이미지 프레임 수 기준
    total_q_in = float(filtered["q_in_total"].sum())
    pure_milk = float(filtered[filtered["contamination"] == "no"]["q_in_total"].sum())
    milk_water = float(filtered[filtered["contamination"] == "chem"]["q_in_total"].sum())
    milk_water_glucose = float(filtered[filtered["contamination"] == "bio"]["q_in_total"].sum())
    # 출하량은 "정상 배치(출하 가능)" 기준으로 집계 (최종제품공정은 배치 단위 판정)
    shipment_volume = 0.0
    if not filtered.empty:
        batch_summary = get_final_product_batch_summary_frame()
        if not batch_summary.empty:
            ok_batches = set(batch_summary[batch_summary["shipment_ok"].eq(True)]["batch_id"].astype(int).tolist())
            shipment_volume = float(filtered[filtered["batch_id"].astype(int).isin(ok_batches)]["q_in_total"].sum())
    
    return {
        "total_samples": total_samples,
        "clean_samples": clean_samples,
        "contaminated": contaminated,
        "pass_rate": pass_rate,
        "high_risk": high_risk,
        "total_q_in": total_q_in,
        "pure_milk": pure_milk,
        "milk_water": milk_water,
        "milk_water_glucose": milk_water_glucose,
        "shipment_volume": shipment_volume,
    }


def inspection_ph_figure(period: str):
    filtered = _filter_summary(period)
    fig = go.Figure()
    fig.add_trace(
        go.Histogram(
            x=filtered["final_ph"],
            nbinsx=20,
            marker=dict(color="#14b8a6"),
            hovertemplate="pH %{x:.2f}<br>배치 %{y}건<extra></extra>",
        )
    )
    fig.add_vrect(x0=6.6, x1=6.8, fillcolor="rgba(34, 197, 94, 0.10)", line_width=0)
    fig.update_layout(
        height=340,
        margin=dict(l=40, r=20, t=20, b=40),
        xaxis_title="최종 pH",
        yaxis_title="배치 수",
        plot_bgcolor="white",
        paper_bgcolor="white",
        bargap=0.08,
    )
    return fig


def inspection_contamination_figure(period: str):
    filtered = _filter_final_inspection_summary(period)
    counts = filtered["contamination"].value_counts().reindex(["no", "chem", "bio"], fill_value=0)
    labels = ["정상", "의심", "불량"]
    colors = ["#22c55e", "#f59e0b", "#ef4444"]
    
    fig = go.Figure(
        data=[
            go.Pie(
                labels=labels,
                values=counts.values,
                hole=0.55,
                marker=dict(colors=colors),
                textinfo="label+percent",
                textposition="auto",
                hovertemplate="<b>%{label}</b><br>배치: %{value}개<br>비율: %{percent}<extra></extra>",
            )
        ]
    )
    fig.update_layout(
        height=340,
        margin=dict(l=20, r=20, t=40, b=20),
        paper_bgcolor="white",
        font=dict(size=12, color="#374151"),
        annotations=[
            dict(
                text="제품 상태",
                x=0.5, y=0.5,
                font_size=14,
                showarrow=False,
            )
        ]
    )
    return fig


def get_final_inspection_batch_round_summary(
    period: str,
    batch_ids: list[int] | None = None,
    rounds: int = 10,
    batch_count: int = 3,
    target_date: str | None = None,
):
    """
    최종검사(이미지) 데이터를 운영 배치(BATCH-###) 단위로 집계하고,
    일일 2시간 로트 순번 1~10 기준으로 로트별 부적합 구성을 계산합니다.

    - batch_ids가 없으면 운영 배치 Top N(batch_count)로 자동 선택합니다.
    - 랜덤 샘플링은 사용하지 않습니다(이미지 레코드에 이미 결정적 매핑 완료).
    """
    filtered = _apply_final_inspection_date_filter(_filter_final_inspection_summary(period), target_date)
    if filtered.empty:
        return []

    rounds = int(rounds) if rounds and int(rounds) > 0 else get_configured_runs_per_day()
    frame = filtered.copy()
    run_source = "line_run" if "line_run" in frame.columns else "checkpoint"
    if run_source not in frame.columns:
        frame[run_source] = 1
    frame["run_number"] = pd.to_numeric(frame[run_source], errors="coerce").fillna(1).astype(int).clip(lower=1, upper=rounds)
    if "line_id" not in frame.columns:
        frame["line_id"] = 1
    frame["line_id"] = pd.to_numeric(frame["line_id"], errors="coerce").fillna(1).astype(int)
    if frame.empty:
        return []

    grouped = (
        frame.groupby(["line_id", "run_number"], as_index=False)
        .agg(
            batch_id=("batch_id", "first"),
            batch_name=("batch_name", "first"),
            total=("q_in_total", "sum"),
            no_count=("contamination", lambda s: int(pd.Series(s).eq("no").sum())),
            chem_count=("contamination", lambda s: int(pd.Series(s).eq("chem").sum())),
            bio_count=("contamination", lambda s: int(pd.Series(s).eq("bio").sum())),
            line_day=("line_day", "first"),
        )
        .sort_values(["line_id", "run_number"])
        .reset_index(drop=True)
    )
    grouped["suspect_count"] = grouped["chem_count"]
    grouped["confirmed_nonconforming_count"] = grouped["bio_count"]
    grouped["defect_count"] = grouped["suspect_count"] + grouped["confirmed_nonconforming_count"]
    grouped["defect_rate"] = grouped.apply(
        lambda row: (float(row["defect_count"]) / float(row["total"]) * 100.0) if float(row["total"]) else 0.0,
        axis=1,
    )

    decisions = grouped.apply(
        lambda row: classify_final_product_batch(
            confirmed_nonconforming_count=int(row["confirmed_nonconforming_count"]),
            suspect_count=int(row["suspect_count"]),
            sample_count=int(float(row["total"])),
        ),
        axis=1,
    )
    grouped["risk_level"] = [d.level for d in decisions]
    grouped["status"] = [d.disposition for d in decisions]

    summary = []
    configured_lines = get_configured_line_count()
    for line_id in range(1, configured_lines + 1):
        line_slice = grouped[grouped["line_id"] == line_id].copy()
        for run_number in range(1, rounds + 1):
            row_slice = line_slice[line_slice["run_number"] == run_number]
            if row_slice.empty:
                summary.append(
                    {
                        "line_index": line_id,
                        "batch_id": None,
                        "batch_name": None,
                        "batch_short": f"라인 {line_id}",
                        "round": run_number,
                        "run_number": run_number,
                        "line_id": line_id,
                        "line_day": None,
                        "total": 0,
                        "no_count": 0,
                        "chem_count": 0,
                        "bio_count": 0,
                        "suspect_count": 0,
                        "confirmed_nonconforming_count": 0,
                        "defect_count": 0,
                        "defect_rate": 0.0,
                        "risk_level": "정상",
                        "status": "출하 가능",
                        "round_time_label": f"로트 {run_number}",
                    }
                )
                continue

            row = row_slice.iloc[0]
            summary.append(
                {
                    "line_index": line_id,
                    "batch_id": int(row["batch_id"]) if pd.notna(row["batch_id"]) else None,
                    "batch_name": str(row["batch_name"]) if pd.notna(row["batch_name"]) else None,
                    "batch_short": f"라인 {line_id}",
                    "round": int(row["run_number"]),
                    "run_number": int(row["run_number"]),
                    "line_id": line_id,
                    "line_day": int(row["line_day"]) if pd.notna(row["line_day"]) else None,
                    "total": int(float(row["total"])),
                    "no_count": int(float(row["no_count"])),
                    "chem_count": int(float(row["chem_count"])),
                    "bio_count": int(float(row["bio_count"])),
                    "suspect_count": int(float(row.get("suspect_count", 0) or 0)),
                    "confirmed_nonconforming_count": int(float(row.get("confirmed_nonconforming_count", 0) or 0)),
                    "defect_count": int(float(row["defect_count"])),
                    "defect_rate": float(row["defect_rate"]),
                    "risk_level": str(row.get("risk_level") or "정상"),
                    "status": str(row.get("status") or "출하 가능"),
                    "round_time_label": f"로트 {int(row['run_number'])}",
                }
            )

    return summary


def inspection_batch_defect_flow_figure(
    period: str,
    selected_batch: int | None = None,
    selected_round: int | None = None,
    batch_ids: list[int] | None = None,
    batch_count: int = 3,
    rounds: int = 10,
    target_date: str | None = None,
) -> go.Figure:
    """
    최종검사 흐름 그래프: x축은 일일 2시간 로트 순번, 점은 운영 배치 N개.
    y축은 로트 순번별 부적합 수(chem+bio).
    """
    # 대시보드 "현재 시점" 기준으로 최종검사 확정 결과는 완료된 로트까지만 존재해야 한다.
    # (예: 현재 8번째 로트 공정 진행 중이면 1~7만 확정 결과, 8은 검사 대기)
    current_lot: int | None = None
    try:
        from haccp_dashboard.lib.main_helpers import get_dashboard_current_lot_index

        current_lot = int(get_dashboard_current_lot_index())
    except Exception:
        current_lot = None

    display_rounds = int(rounds)
    completed_rounds = int(rounds)
    if current_lot is not None and 1 <= int(current_lot) <= int(rounds):
        display_rounds = min(int(rounds), int(current_lot))
        completed_rounds = max(0, display_rounds - 1)

    point_summary = get_final_inspection_batch_round_summary(
        period,
        batch_ids=batch_ids,
        batch_count=batch_count,
        rounds=display_rounds,
        target_date=target_date,
    )
    title_suffix = f" · {target_date}" if target_date else ""
    if not point_summary:
        fig = go.Figure()
        fig.update_layout(
            title=f"일일 2시간 로트 최종검사 부적합 현황{title_suffix}",
            height=320,
            margin=dict(l=52, r=20, t=48, b=40),
            xaxis=dict(title="일일 2시간 로트 순번", dtick=1, range=[0.7, display_rounds + 0.3]),
            yaxis=dict(title="부적합 수(건)"),
            plot_bgcolor="white",
            paper_bgcolor="white",
            annotations=[dict(text="데이터 없음", x=0.5, y=0.5, xref="paper", yref="paper", showarrow=False, font=dict(size=14, color="#9ca3af"))],
        )
        return fig

    x_values = list(range(1, display_rounds + 1))
    active_line_ids = []
    for item in point_summary:
        if item.get("line_id") is not None and int(item["line_id"]) not in active_line_ids:
            active_line_ids.append(int(item["line_id"]))

    x_tick_labels = [f"로트 {value}" for value in x_values]

    fig = go.Figure()
    for line_id in active_line_ids:
        line_points = [item for item in point_summary if int(item["line_id"]) == int(line_id)]
        line_points = sorted(line_points, key=lambda item: item["round"])
        # 현재 로트(검사 대기)는 확정 결과가 아니므로 선/점에서 제외한다.
        if current_lot is not None and completed_rounds >= 0:
            line_points = [item for item in line_points if int(item.get("round", 0) or 0) <= int(completed_rounds)]
        accent = MAIN_FACTORY_BATCH_META.get(f"batch_{int(line_id):02d}", {}).get("accent", "#2563eb")
        line_label = f"라인 {line_id}"
        has_selected_batch = selected_batch is not None
        line_opacity = 1.0 if (not has_selected_batch or any(item.get("batch_id") == selected_batch for item in line_points)) else 0.22

        custom_data = [
            [
                item["batch_id"],
                item["round"],
                item["total"],
                item["no_count"],
                item.get("suspect_count", item.get("chem_count", 0)),
                item.get("confirmed_nonconforming_count", item.get("bio_count", 0)),
                item["defect_count"],
                item["defect_rate"],
                item.get("risk_level", "정상"),
                item.get("status", "출하 가능"),
                item.get("round_time_label", "--:--"),
                item.get("line_id"),
                item.get("batch_name"),
            ]
            for item in line_points
        ]

        x_batch = [item["round"] for item in line_points]
        y_values = [item["defect_count"] for item in line_points]
        marker_sizes = [12 + min(float(item["defect_rate"]) / 8.0, 16.0) for item in line_points]
        def _status_color(item: dict) -> str:
            if (
                selected_batch is not None
                and item.get("batch_id") is not None
                and int(selected_batch) == int(item["batch_id"])
                and selected_round == item["round"]
            ):
                return "#111827"
            level = str(item.get("risk_level") or "")
            if level == "위험":
                return "#ef4444"
            if level == "경고":
                return "#f59e0b"
            return "#22c55e"

        marker_colors = [_status_color(item) for item in line_points]
        marker_line_widths = [
            2 if (selected_batch is not None and item.get("batch_id") is not None and int(selected_batch) == int(item["batch_id"]) and selected_round == item["round"]) else 1
            for item in line_points
        ]
        text_values = [str(item.get("batch_name") or "") for item in line_points]

        fig.add_trace(
            go.Scatter(
                x=x_batch,
                y=y_values,
                mode="lines+markers",
                line=dict(color=accent, width=3),
                opacity=line_opacity,
                marker=dict(
                    size=marker_sizes,
                    color=marker_colors,
                    line=dict(color="#ffffff", width=marker_line_widths),
                ),
                text=text_values,
                customdata=custom_data,
                name=line_label,
                hovertemplate=(
                    f"{line_label}<br>"
                    "배치 %{customdata[12]}<br>"
                    "일일 2시간 로트 %{customdata[1]}<br>"
                    "판정: <b>%{customdata[8]}</b> (%{customdata[9]})<br>"
                    "확정 부적합: %{customdata[5]}건 · 의심: %{customdata[4]}건<br>"
                    "이상 샘플 합계: <b>%{y}건</b><br>"
                    "총 검사: %{customdata[2]}건<br>"
                    "부적합률: %{customdata[7]:.1f}%<extra></extra>"
                ),
            )
        )

    warning_threshold = 1
    max_defect = max(
        [
            int(item.get("defect_count", 0) or 0)
            for item in point_summary
            if int(item.get("round", 0) or 0) <= int(completed_rounds)
        ],
        default=0,
    )
    y_lower = 0
    y_upper = 3

    if current_lot is not None and 1 <= int(current_lot) <= int(rounds):
        title_text = f"일일 2시간 로트 1~{int(completed_rounds)} 기준 최종검사(배치) 판정 현황{title_suffix}"
    else:
        title_text = f"일일 2시간 로트 {int(rounds)}개 기준 최종검사(배치) 판정 현황{title_suffix}"

    fig.update_layout(
        title=dict(text=title_text, x=0, font=dict(size=16, color="#1f2937")),
        height=320,
        margin=dict(l=56, r=24, t=52, b=42),
        xaxis=dict(
            title="일일 2시간 로트 순번",
            tickmode="array",
            tickvals=x_values,
            ticktext=x_tick_labels,
            range=[0.7, display_rounds + 0.3],
            showgrid=True,
            gridcolor="#eef2f7",
            tickangle=-18,
        ),
        yaxis=dict(
            title="이상 샘플 수(건)",
            range=[y_lower, y_upper],
            dtick=1,
            showgrid=True,
            gridcolor="#eef2f7",
        ),
        plot_bgcolor="white",
        paper_bgcolor="white",
        hovermode="closest",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
    )

    # 경고 기준(의심 샘플 1건 이상) 안내선
    fig.add_hline(
        y=warning_threshold,
        line=dict(color="rgba(245, 158, 11, 0.55)", width=2, dash="dot"),
        annotation_text="경고 기준 1건",
        annotation_position="top right",
        annotation_font=dict(size=11, color="#b45309"),
    )

    # 현재 로트(공정 진행 중) 표시: 최종검사 확정 결과에는 포함하지 않되 "검사 대기" 상태를 안내한다.
    try:
        from haccp_dashboard.lib.main_helpers import get_dashboard_current_lot_index

        current_lot = int(get_dashboard_current_lot_index())
        if 1 <= current_lot <= int(display_rounds):
            fig.add_vline(
                x=current_lot,
                line=dict(color="rgba(251, 146, 60, 0.7)", width=2, dash="dot"),
            )
            fig.add_annotation(
                x=current_lot,
                y=1.02,
                xref="x",
                yref="paper",
                text="현재 로트: 검사 대기",
                showarrow=False,
                font=dict(size=12, color="#c2410c"),
                bgcolor="rgba(255, 247, 237, 0.95)",
                bordercolor="rgba(251, 146, 60, 0.45)",
                borderwidth=1,
                borderpad=6,
            )
    except Exception:
        pass

    return fig


def get_final_inspection_rows(period: str, target_date: str | None = None):
    """
    최종검사 기록 테이블용(페이지 하단):
    - 이미지 1장 단위가 아니라, 운영 배치(BATCH-###) 단위로 요약해 반환합니다.
    """
    filtered = _apply_final_inspection_date_filter(_filter_final_inspection_summary(period), target_date)
    if filtered.empty:
        return []

    frame = filtered.copy()
    frame["date"] = pd.to_datetime(frame["date"]).dt.date
    contamination_worst = frame.groupby(["date", "batch_id"], as_index=False).agg(
        batch_name=("batch_name", "first"),
        report_id=("report_id", "first"),
        final_ph=("final_ph", "mean"),
        final_temp=("final_temp", "mean"),
        stability_score=("stability_score", "mean"),
        suspect_count=("contamination", lambda s: int(pd.Series(s).eq("chem").sum())),
        confirmed_nonconforming_count=("contamination", lambda s: int(pd.Series(s).eq("bio").sum())),
        total_images=("q_in_total", "sum"),
        pass_images=("q_out_total", "sum"),
    )

    def _worst_contamination(row):
        if int(row["confirmed_nonconforming_count"]) >= 1:
            return "bio"
        if int(row["suspect_count"]) >= 1:
            return "chem"
        return "no"

    contamination_worst["contamination"] = contamination_worst.apply(_worst_contamination, axis=1)
    decisions = contamination_worst.apply(
        lambda r: classify_final_product_batch(
            confirmed_nonconforming_count=int(r["confirmed_nonconforming_count"]),
            suspect_count=int(r["suspect_count"]),
            sample_count=int(float(r["total_images"])),
        ),
        axis=1,
    )
    contamination_worst["risk_level"] = [d.level for d in decisions]
    contamination_worst["status"] = [d.disposition for d in decisions]
    contamination_worst.loc[contamination_worst["risk_level"].eq("정상"), "status"] = "PASS"
    contamination_worst["contamination_label"] = contamination_worst["contamination"].map(lambda v: CONTAMINATION_LABELS.get(v, v))

    rows = []
    view = contamination_worst.sort_values(["date", "batch_id"], ascending=[False, False]).head(60)
    for row in view.itertuples(index=False):
        bid = int(row.batch_id)
        line_no = (bid % 3) + 1
        date_compact = str(row.date).replace("-", "")
        hh = 8 + (bid * 7) % 12  # 08~19시
        mm = (bid * 13) % 60
        report_id_str = f"L{line_no} - {date_compact}.{hh:02d}:{mm:02d}"
        rows.append(
            {
                "date": str(row.date),
                "batch_name": str(row.batch_name),
                "report_id": report_id_str,
                "contamination_label": CONTAMINATION_LABELS.get(str(row.contamination), str(row.contamination)),
                "final_ph": float(row.final_ph),
                "final_temp": float(row.final_temp),
                "stability_score": float(row.stability_score),
                "status": str(row.status),
                "risk_level": str(getattr(row, "risk_level", "정상")),
            }
        )
    return rows


MAIN_INSPECTION_CATEGORY_ORDER = ["no", "chem", "bio"]
MAIN_INSPECTION_CATEGORY_META = {
    "no": {
        "line_label": "IMG A",
        "title": "순수우유",
        "status": "정상",
        "focus": "출하 가능",
        "accent": "#22c55e",
        "fill": "rgba(34, 197, 94, 0.14)",
    },
    "chem": {
        "line_label": "IMG B",
        "title": "우유 + 물",
        "status": "경고",
        "focus": "재검 필요",
        "accent": "#f59e0b",
        "fill": "rgba(245, 158, 11, 0.14)",
    },
    "bio": {
        "line_label": "IMG C",
        "title": "우유 + 물 + 포도당",
        "status": "위험",
        "focus": "출하 보류",
        "accent": "#ef4444",
        "fill": "rgba(239, 68, 68, 0.14)",
    },
}

MAIN_FACTORY_BATCH_META = {
    "batch_01": {
        "label": "배치 01",
        "short": "1호",
        "accent": "#38bdf8",
        "fill": "rgba(56, 189, 248, 0.20)",
        "glow": "rgba(56, 189, 248, 0.34)",
    },
    "batch_02": {
        "label": "배치 02",
        "short": "2호",
        "accent": "#f59e0b",
        "fill": "rgba(245, 158, 11, 0.20)",
        "glow": "rgba(245, 158, 11, 0.34)",
    },
    "batch_03": {
        "label": "배치 03",
        "short": "3호",
        "accent": "#ef4444",
        "fill": "rgba(239, 68, 68, 0.20)",
        "glow": "rgba(239, 68, 68, 0.34)",
    },
}


def get_main_operational_batch_ids(limit: int = 3) -> list[int]:
    items = get_hidden_anomaly_batch_items(limit=max(int(limit), 0))
    batch_ids = [int(item["batch_id"]) for item in items if "batch_id" in item]
    if batch_ids:
        return batch_ids

    summary = _filter_summary("week")
    if summary.empty:
        summary = get_batch_summary_frame()
    return [int(row.batch_id) for row in summary.head(max(int(limit), 0)).itertuples(index=False)]


_OPERATION_STATUS_META = {
    "stable": {
        "label": "정상",
        "accent": "#0f766e",
        "fill": "rgba(15, 118, 110, 0.22)",
        "glow": "rgba(15, 118, 110, 0.34)",
    },
    "warning": {
        "label": "경고",
        "accent": "#f59e0b",
        "fill": "rgba(245, 158, 11, 0.20)",
        "glow": "rgba(245, 158, 11, 0.34)",
    },
    "critical": {
        "label": "위험",
        "accent": "#ef4444",
        "fill": "rgba(239, 68, 68, 0.20)",
        "glow": "rgba(239, 68, 68, 0.34)",
    },
}

MAIN_PROCESS_STAGE_ORDER = list(STATE_ORDER)
MAIN_PROCESS_STAGE_META = {
    state: {"label": STATE_LABELS[state], "english": state}
    for state in MAIN_PROCESS_STAGE_ORDER
}


def _derive_operational_status_key(sensor_warning: int, sensor_danger: int) -> str:
    if sensor_danger > max(sensor_warning, 0) and sensor_danger > 0:
        return "critical"
    if sensor_warning > 0:
        return "warning"
    return "stable"


def _format_duration_minutes(duration_minutes: int) -> str:
    hours = max(int(duration_minutes), 0) // 60
    minutes = max(int(duration_minutes), 0) % 60
    return f"{hours}h {minutes}m"


def _build_main_process_card_summary(batch_id: int, target_date: str | None, snapshot_ratio: float, line_index: int) -> dict:
    del target_date
    batch_id = int(batch_id)
    process_frame = _load_process_dataframe()
    batch_frame = process_frame[process_frame["batch_id"] == batch_id].sort_values("datetime").reset_index(drop=True)
    if batch_frame.empty:
        return {
            "batch_id": batch_id,
            "line_id": line_index,
            "status_key": "stable",
            "status_label": _OPERATION_STATUS_META["stable"]["label"],
            "current_state": "Receiving",
            "current_stage_label": MAIN_PROCESS_STAGE_META["Receiving"]["label"],
            "current_stage_english": MAIN_PROCESS_STAGE_META["Receiving"]["english"],
            "stage_index": 0,
            "stage_number": 1,
            "stage_total": len(MAIN_PROCESS_STAGE_ORDER),
            "start_time_text": "--:--",
            "elapsed_text": "0h 0m",
            "production_liters": 0.0,
            "temperature": 0.0,
            "ph": 0.0,
            "density": 0.0,
        }

    cutoff_index = max(1, int(len(batch_frame) * float(snapshot_ratio)))
    batch_slice = batch_frame.iloc[:cutoff_index].copy()
    last_row = batch_slice.iloc[-1]

    current_state = str(last_row.get("state") or "Receiving")
    if current_state not in MAIN_PROCESS_STAGE_ORDER:
        current_state = "Receiving"
    stage_index = MAIN_PROCESS_STAGE_ORDER.index(current_state)
    stage_meta = MAIN_PROCESS_STAGE_META[current_state]

    start_time = batch_frame.iloc[0]["datetime"]
    current_time = last_row["datetime"]
    duration_minutes = int(max((current_time - start_time).total_seconds() / 60.0, 0.0))
    line_id = int(last_row.get("line_id")) if pd.notna(last_row.get("line_id")) else line_index

    mix_metrics = _get_sensor_mix_metrics(batch_frame)
    sensor_normal = int(mix_metrics["normal_count"])
    sensor_warning = int(mix_metrics["warning_count"])
    sensor_danger = int(mix_metrics["danger_count"])

    status_key = _derive_operational_status_key(sensor_warning, sensor_danger)

    production_liters = float(batch_slice["Q_in"].sum()) if "Q_in" in batch_slice.columns else 0.0
    temperature = float(last_row.get("T") or 0.0)
    ph = float(last_row.get("pH") or 0.0)
    density = float(last_row.get("Mu") or 0.0)

    return {
        "batch_id": batch_id,
        "batch_name": f"BATCH-{batch_id:03d}",
        "batch_date": str(pd.to_datetime(batch_frame.iloc[0]["date"]).date()) if "date" in batch_frame.columns else None,
        "line_id": line_id,
        "line_run": int(last_row.get("line_run")) if pd.notna(last_row.get("line_run")) else None,
        "line_day": int(last_row.get("line_day")) if pd.notna(last_row.get("line_day")) else None,
        "status_key": status_key,
        "status_label": _OPERATION_STATUS_META[status_key]["label"],
        "current_state": current_state,
        "current_stage_label": stage_meta["label"],
        "current_stage_english": stage_meta["english"],
        "stage_index": stage_index,
        "stage_number": stage_index + 1,
        "stage_total": len(MAIN_PROCESS_STAGE_ORDER),
        "start_time_text": pd.Timestamp(start_time).strftime("%H:%M"),
        "elapsed_text": _format_duration_minutes(duration_minutes),
        "sensor_normal_count": sensor_normal,
        "sensor_warning_count": sensor_warning,
        "sensor_danger_count": sensor_danger,
        "production_liters": production_liters,
        "temperature": temperature,
        "ph": ph,
        "density": density,
    }


def build_main_operational_sampling_badge(limit: int = 3, target_date: str | None = None):
    target_date = _resolve_main_operational_date(target_date, "week")
    batch_ids = get_main_final_inspection_batch_ids(limit=limit, period="week", target_date=target_date)
    snapshot = _get_main_operational_status_snapshot(target_date, "week")
    configured_runs = get_configured_runs_per_day()
    configured_lines = get_configured_line_count()
    if not batch_ids and snapshot["batch_total"] <= 0:
        return [html.Span("운영 배치 0", className="factory-data-chip")]

    process_day_frame = _get_main_operational_day_frame(target_date, "week")
    batch_slice = process_day_frame[process_day_frame["batch_id"].isin(batch_ids)].copy() if not process_day_frame.empty else process_day_frame
    sensor_normal, sensor_warning, sensor_danger = count_rows_by_threshold(batch_slice) if not batch_slice.empty else (0, 0, 0)

    return [
        html.Span(f"전체 운영 배치 {snapshot['batch_total']}개", className="factory-data-chip"),
        html.Span(f"정상·경고·위험 혼합 대표 배치 {len(batch_ids)}개", className="factory-data-chip"),
        html.Span(f"운영 기준 {configured_lines}개 라인 · 하루 {configured_runs}회 생산", className="factory-data-chip"),
        html.Span(f"기준일 {target_date or '-'}", className="factory-data-chip accent"),
        html.Span(f"센서 기준 정상 {sensor_normal:,} · 경고 {sensor_warning:,} · 위험 {sensor_danger:,}", className="factory-data-chip live"),
    ]


def build_main_operational_graph_badge(selected_batch: int | None = None, limit: int = 3, target_date: str | None = None):
    del selected_batch, limit
    target_date = _resolve_main_operational_date(target_date, "week")
    snapshot = _get_main_operational_status_snapshot(target_date, "week")
    configured_runs = get_configured_runs_per_day()
    configured_lines = get_configured_line_count()
    kpi_items = snapshot["kpi_items"]
    production_value = kpi_items[0]["value"] if len(kpi_items) > 0 else "0 L"
    ccp_value = kpi_items[1]["value"] if len(kpi_items) > 1 else "0"
    shipment_value = kpi_items[2]["value"] if len(kpi_items) > 2 else "0"
    high_risk_value = kpi_items[3]["value"] if len(kpi_items) > 3 else "0"

    return [
        html.Span(f"기준일 {target_date or '-'}", className="factory-data-chip accent"),
        html.Span(f"운영 기준 {configured_lines}개 라인 · 하루 {configured_runs}회 생산 · 운영 배치 {snapshot['batch_total']}개", className="factory-data-chip"),
        html.Span(f"일일 총 생산량 {production_value}", className="factory-data-chip"),
        html.Span(f"CCP 이탈 {ccp_value} · 출하영향 {shipment_value} · 미조치 고위험 {high_risk_value}", className="factory-data-chip live"),
    ]


def build_main_operational_batch_button(summary: dict, selected_batch: int | None = None):
    batch_id = int(summary["batch_id"])
    status_key = str(summary.get("status_key") or "stable")
    meta = _OPERATION_STATUS_META.get(status_key, _OPERATION_STATUS_META["stable"])

    if selected_batch == batch_id:
        selection_class = "is-selected"
    elif selected_batch is not None:
        selection_class = "is-muted"
    else:
        selection_class = "is-ready"

    stage_nodes = []
    current_stage_index = int(summary.get("stage_index") or 0)
    for index, state in enumerate(MAIN_PROCESS_STAGE_ORDER):
        stage_meta = MAIN_PROCESS_STAGE_META[state]
        if index < current_stage_index:
            item_class = "is-complete"
            circle_label = "✓"
        elif index == current_stage_index:
            item_class = "is-active"
            circle_label = str(index + 1)
        else:
            item_class = "is-pending"
            circle_label = ""

        stage_nodes.append(
            html.Div(
                [
                    html.Div(circle_label, className=f"factory-stage-circle {item_class}"),
                    html.Div(
                        [
                            html.Div(stage_meta["label"], className="factory-stage-label-kr"),
                            html.Div(stage_meta["english"], className="factory-stage-label-en"),
                        ],
                        className=f"factory-stage-label {item_class}",
                    ),
                ],
                className="factory-stage-item",
            )
        )
        if index < len(MAIN_PROCESS_STAGE_ORDER) - 1:
            connector_class = "is-complete" if index < current_stage_index else "is-pending"
            stage_nodes.append(html.Div(className=f"factory-stage-connector {connector_class}"))

    return html.Button(
        [
            html.Div(
                [
                    html.Span(f"라인 {int(summary.get('line_id') or 0)}", className="factory-batch-line-chip"),
                    html.Span(meta["label"], className=f"factory-batch-status {status_key}"),
                ],
                className="factory-batch-head",
            ),
            html.Div(
                f"BATCH-{batch_id:03d} · Line {int(summary.get('line_id') or 0)}",
                className="factory-batch-title",
            ),
            html.Div(
                f"기준일 {summary.get('batch_date') or '-'} | 운영일 {int(summary.get('line_day') or 1)}일차 | 일일 2시간 로트 {int(summary.get('line_run') or 1)}/{get_configured_runs_per_day()} | 시작 {summary.get('start_time_text', '--:--')} | 현재 단계 {summary.get('current_stage_label', '-') } / {summary.get('current_stage_english', '-')}",
                className="factory-batch-meta",
            ),
            html.Div(
                stage_nodes,
                className="factory-stage-track",
            ),
            html.Div(
                f"현재 공정 단계: {summary.get('current_stage_label', '-')} / {summary.get('current_stage_english', '-')} ({int(summary.get('stage_number') or 1)}/{int(summary.get('stage_total') or len(MAIN_PROCESS_STAGE_ORDER))}) · 일일 2시간 로트 {int(summary.get('line_run') or 1)}/{get_configured_runs_per_day()}",
                className="factory-stage-current",
            ),
            html.Div(
                [
                    html.Div(
                        [
                            html.Div("센서 기준 상태 분포", className="factory-mini-section-title"),
                            html.Div(
                                [
                                    html.Div([html.Span("정상"), html.Strong(f"{int(summary.get('sensor_normal_count') or 0)}")], className="factory-mini-metric stable"),
                                    html.Div([html.Span("경고"), html.Strong(f"{int(summary.get('sensor_warning_count') or 0)}")], className="factory-mini-metric warning"),
                                    html.Div([html.Span("위험"), html.Strong(f"{int(summary.get('sensor_danger_count') or 0)}")], className="factory-mini-metric critical"),
                                ],
                                className="factory-mini-metric-row",
                            ),
                        ],
                        className="factory-mini-section",
                    ),
                ],
                className="factory-batch-metrics",
            ),
            html.Div(
                f"생산량 {float(summary.get('production_liters') or 0.0):.0f}L / 온도 {float(summary.get('temperature') or 0.0):.1f}℃ / pH {float(summary.get('ph') or 0.0):.2f} / 밀도 {float(summary.get('density') or 0.0):.2f}",
                className="factory-batch-footer",
            ),
        ],
        id={"type": "main-batch-button", "index": batch_id},
        n_clicks=0,
        className=f"factory-batch-node {selection_class} {status_key}",
    )


def build_main_operational_pipeline_buttons(selected_batch: int | None = None, limit: int = 3, target_date: str | None = None):
    target_date = _resolve_main_operational_date(target_date, "week")
    batch_ids = get_main_final_inspection_batch_ids(limit=limit, period="week", target_date=target_date)
    summaries = []
    for index, batch_id in enumerate(batch_ids, start=1):
        ratio = SNAPSHOT_RATIOS[min(index - 1, len(SNAPSHOT_RATIOS) - 1)] if SNAPSHOT_RATIOS else 0.55
        summaries.append(_build_main_process_card_summary(batch_id, target_date, ratio, index))

    return [build_main_operational_batch_button(summary, selected_batch) for summary in summaries]


def build_main_checkpoint_anomaly_figure(selected_batch: int | None = None, limit: int = 3, target_date: str | None = None):
    del limit
    target_date = _resolve_main_operational_date(target_date, "week")
    run_total = get_configured_runs_per_day()

    if selected_batch is not None:
        try:
            selected_batch = int(selected_batch)
        except Exception:
            selected_batch = None

    if selected_batch is not None:
        process_frame = _load_process_dataframe().copy()
        batch_frame = process_frame[process_frame["batch_id"] == selected_batch].sort_values("datetime").reset_index(drop=True)
        records = []
        for segment_index in range(1, run_total + 1):
            start_index = int((segment_index - 1) * len(batch_frame) / run_total)
            end_index = int(segment_index * len(batch_frame) / run_total)
            if end_index <= start_index:
                end_index = min(len(batch_frame), start_index + 1)
            segment_frame = batch_frame.iloc[start_index:end_index].copy() if not batch_frame.empty else batch_frame
            normal_count, warning_count, danger_count = count_rows_by_threshold(segment_frame)
            batch_total = normal_count + warning_count + danger_count
            for status_key, status_label, count_value in [
                ("normal", "정상", normal_count),
                ("warning", "경고", warning_count),
                ("danger", "위험", danger_count),
            ]:
                records.append(
                    {
                        "run_number": segment_index,
                        "status_key": status_key,
                        "status_label": status_label,
                        "count": int(count_value),
                        "batch_total": int(batch_total),
                        "share_pct": (float(count_value) / float(batch_total) * 100.0) if batch_total else 0.0,
                        "top_batches": f"BATCH-{selected_batch:03d}",
                    }
                )
        flow_frame = pd.DataFrame(records)
    else:
        flow_frame = get_main_operational_status_flow_frame(target_date, "week")

    if not target_date or flow_frame.empty:
        figure = go.Figure()
        figure.update_layout(
            height=370,
            margin=dict(l=50, r=24, t=24, b=48),
            plot_bgcolor="rgba(0,0,0,0)",
            paper_bgcolor="rgba(0,0,0,0)",
            annotations=[
                dict(
                    text="표시할 운영 배치 데이터가 없습니다.",
                    x=0.5,
                    y=0.5,
                    xref="paper",
                    yref="paper",
                    showarrow=False,
                    font=dict(size=16, color="#475569"),
                )
            ],
        )
        return figure

    figure = go.Figure()
    status_styles = [
        ("normal", "정상", "rgba(110, 167, 111, 0.92)", "rgba(133, 211, 151, 0.78)"),
        ("warning", "경고", "rgba(244, 162, 75, 0.92)", "rgba(255, 203, 132, 0.82)"),
        ("danger", "위험", "rgba(241, 90, 90, 0.9)", "rgba(255, 124, 124, 0.84)"),
    ]

    for status_key, status_label, line_color, fill_color in status_styles:
        status_frame = flow_frame[flow_frame["status_key"] == status_key].sort_values("run_number")
        x_values = status_frame["run_number"].tolist()
        y_values = status_frame["count"].tolist()
        custom_data = [
            [
                int(row["count"]),
                float(row["share_pct"]),
                row["top_batches"],
                int(row["batch_total"]),
            ]
            for row in status_frame.to_dict("records")
        ]

        figure.add_trace(
            go.Scatter(
                x=x_values,
                y=y_values,
                mode="lines",
                name=status_label,
                stackgroup="operational-status",
                groupnorm="",
                line=dict(color="rgba(0,0,0,0)", width=0, shape="linear"),
                fillcolor=fill_color,
                customdata=custom_data,
                hovertemplate=(
                    f"{status_label}<br>"
                    "일일 2시간 로트 %{x}<br>"
                    "해당 로트 배치 %{customdata[3]}개 중 %{customdata[0]}개 (%{customdata[1]:.0f}%)<br>"
                    "주요 배치 %{customdata[2]}<extra></extra>"
                ),
            )
        )

    figure.update_layout(
        height=430,
        margin=dict(l=58, r=28, t=24, b=58),
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
        hovermode="x unified",
        legend=dict(orientation="h", yanchor="top", y=-0.16, xanchor="left", x=0, font=dict(size=12)),
        xaxis=dict(
            title="선택 배치 공정 진행 구간" if selected_batch is not None else "일일 2시간 로트 순번",
            tickmode="array",
            tickvals=list(range(1, run_total + 1)),
            ticktext=[f"구간 {value}" for value in range(1, run_total + 1)] if selected_batch is not None else [f"로트 {value}" for value in range(1, run_total + 1)],
            range=[0.5, run_total + 0.5],
            showgrid=True,
            gridcolor="rgba(203, 213, 225, 0.42)",
            zeroline=False,
            title_font=dict(size=14, color="#374151"),
            tickfont=dict(size=12, color="#475569"),
        ),
        yaxis=dict(
            title="상태별 배치 수",
            rangemode="tozero",
            dtick=1,
            gridcolor="rgba(203, 213, 225, 0.42)",
            zeroline=False,
            title_font=dict(size=14, color="#374151"),
            tickfont=dict(size=12, color="#475569"),
        ),
    )
    return figure

### 공정 흐름도 카드 관련 코드 (함수 밖 최상단으로 이동)
def process_item(img_name, label, active=False):
    return html.Div(
        [
            html.Img(src=f"/assets/{img_name}", className="pf-img"),
            html.Div(label, className="pf-label"),
        ],
        className=" ".join(["pf-item", "is-active" if active else ""]),
    )


def _resolve_active_step_from_data() -> tuple[str, str, int | None]:
    """
    Returns (active_step, state_label, line_id) for the most recent line/batch.
    active_step is one of: truck, tank, filter, standard, heater, hold, cool, filling, inspection, release
    """
    summary = get_batch_summary_frame()
    if summary is None or summary.empty:
        return "heater", "가열", None

    configured_line = get_runtime_env_value("HACCP_DEFAULT_LINE", "1")
    resolved_line: int | None = None
    try:
        resolved_line = int(str(configured_line).strip())
    except Exception:
        resolved_line = None

    view = summary.copy()
    if "end_time" in view.columns:
        view = view.sort_values("end_time", ascending=False)
    elif "start_time" in view.columns:
        view = view.sort_values("start_time", ascending=False)

    if resolved_line is not None and "line_id" in view.columns:
        slice_ = view[view["line_id"].fillna(-1).astype(int) == int(resolved_line)]
        if not slice_.empty:
            view = slice_

    row = view.iloc[0]
    last_state = str(row.get("last_state") or "Receiving")
    line_id_value = row.get("line_id")
    try:
        line_id_int = int(line_id_value) if line_id_value is not None and str(line_id_value).strip() != "" else None
    except Exception:
        line_id_int = None

    # Map internal state -> UI step
    state_key = last_state
    mapping = {
        "Receiving": "truck",
        "Storage": "tank",
        "Filter": "filter",
        "Standardize": "standard",
        "Heat": "heater",
        "Hold": "hold",
        "Cool": "cool",
        "Fill": "filling",
        "Inspect": "inspection",
        "Release": "release",
    }
    active_step = mapping.get(state_key, "heater")
    state_label = str(STATE_LABELS.get(state_key, state_key))
    return active_step, state_label, line_id_int


def build_process_flow(active_step: str = "heater"):
    def arrow():
        return html.Div("→", className="pf-arrow")

    return html.Div(
        [
            process_item("truck.png", "원유 입고", active=(active_step == "truck")),
            arrow(),
            process_item("tank.png", "저장", active=(active_step == "tank")),
            arrow(),
            process_item("filter.png", "여과", active=(active_step == "filter")),
            arrow(),
            process_item("standard.png", "표준화", active=(active_step == "standard")),
            arrow(),
            process_item("heater.png", "가열", active=(active_step == "heater")),
            arrow(),
            process_item("holding.png", "보온", active=(active_step == "hold")),
            arrow(),
            process_item("ct_stage_cool.svg", "냉각", active=(active_step == "cool")),
            arrow(),
            process_item("filling.png", "충진", active=(active_step == "filling")),
            arrow(),
            process_item("inspection.png", "검사", active=(active_step == "inspection")),
            arrow(),
            process_item("output.png", "출하판정", active=(active_step == "release")),
        ],
        className="pf-flow",
    )


def build_process_flow_card() -> html.Div:
    """공정 흐름도 카드: 이미지 기반 공정 흐름(단일 컴포넌트) 표시."""
    active_step, state_label, line_id = _resolve_active_step_from_data()
    subtitle = f"현재 공정: 라인 {line_id} · {state_label}" if line_id is not None else f"현재 공정: {state_label}"
    return html.Div(
        [
            html.Div(
                [
                    html.H2("우유 생산 공정 흐름도", className="smart-panel-title"),
                    html.Div(
                        subtitle,
                        className="factory-graph-description",
                    ),
                ],
                className="smart-panel-head",
            ),
            build_process_flow(active_step=active_step),
        ],
        className="smart-panel process-flow-card",
        style={"marginBottom": "24px"},
    )



# NOTE: The legacy line-summary/process-under demo UI block was removed to enforce
# the project-wide common rules:
# - process/batch invariants: `lib.process_spec`
# - heating sensor risk classification: `lib.heating_risk`
# - final product (image-based) batch disposition: `lib.final_product_risk`
# The removed code used hard-coded temperature/hold-time thresholds and defect-rate heuristics
# that could conflict with the common rules.

def build_main_smart_factory_section():
    initial_date_options = [{"label": value, "value": value} for value in get_main_operational_available_dates("week")]
    initial_target_date = initial_date_options[0]["value"] if initial_date_options else None
    return html.Div(
        [
            # 기존 운영 배치 현황, 파이프라인, 그래프, 배지, 푸트노트 모두 제거됨
        ],
        className="smart-factory-section",
    )


def _main_inspection_filtered_summary(period: str = "week") -> pd.DataFrame:
    filtered = _filter_final_inspection_summary(period)
    if filtered.empty:
        filtered = get_final_inspection_summary_frame()
    return filtered.copy()


def get_main_inspection_category_ids(period: str = "week"):
    filtered = _main_inspection_filtered_summary(period)
    available = set(filtered["contamination"].dropna().tolist())
    return [category for category in MAIN_INSPECTION_CATEGORY_ORDER if category in available]


def _main_inspection_button_payload(contamination: str, period: str = "week"):
    filtered = _main_inspection_filtered_summary(period)
    rows = filtered[filtered["contamination"] == contamination].copy()
    meta = MAIN_INSPECTION_CATEGORY_META[contamination]
    total_frames = float(rows["q_in_total"].sum()) if not rows.empty else 0.0
    shipment_frames = float(rows["q_out_total"].sum()) if not rows.empty else 0.0
    avg_ph = float(rows["final_ph"].mean()) if not rows.empty else 0.0
    avg_temp = float(rows["final_temp"].mean()) if not rows.empty else 0.0
    sample_count = int(len(rows))

    return {
        "id": contamination,
        "batch_name": meta["title"],
        "line_label": meta["line_label"],
        "status": meta["status"],
        "focus": meta["focus"],
        "summary": f"5일 누적 {total_frames:.0f}장 · 출하 가능 {shipment_frames:.0f}장",
        "indicators": [
            f"배치 {sample_count}건",
            f"평균 pH {avg_ph:.2f}",
            f"평균 온도 {avg_temp:.1f}℃",
        ],
    }


def build_main_final_inspection_figure(contamination: str, period: str = "week"):
    filtered = _main_inspection_filtered_summary(period)
    rows = filtered[filtered["contamination"] == contamination].copy()
    meta = MAIN_INSPECTION_CATEGORY_META[contamination]
    grouped = (
        rows.groupby("date", as_index=False)
        .agg(
            total_frames=("q_in_total", "sum"),
            shipment_frames=("q_out_total", "sum"),
            avg_ph=("final_ph", "mean"),
        )
        .sort_values("date")
    )

    x_values = [str(value) for value in grouped["date"].tolist()]
    total_frames = grouped["total_frames"].tolist()
    shipment_frames = grouped["shipment_frames"].tolist()
    avg_ph = grouped["avg_ph"].tolist()

    figure = go.Figure()
    figure.add_trace(
        go.Scatter(
            x=x_values,
            y=total_frames,
            mode="lines+markers+text",
            text=[f"{value:.0f}" for value in total_frames],
            textposition="top center",
            line=dict(color=meta["accent"], width=4, shape="spline"),
            marker=dict(size=10, color=meta["accent"], line=dict(color="white", width=2)),
            fill="tozeroy",
            fillcolor=meta["fill"],
            name="검사 프레임",
            hovertemplate="일자 %{x}<br>검사 프레임 %{y:.0f}장<extra></extra>",
        )
    )
    figure.add_trace(
        go.Scatter(
            x=x_values,
            y=shipment_frames,
            mode="lines+markers",
            line=dict(color="#0f172a", width=2, dash="dash"),
            marker=dict(size=8, color="#0f172a"),
            name="출하 가능",
            hovertemplate="일자 %{x}<br>출하 가능 %{y:.0f}장<extra></extra>",
        )
    )
    figure.add_trace(
        go.Scatter(
            x=x_values,
            y=avg_ph,
            mode="lines",
            line=dict(color="#3b82f6", width=2),
            name="평균 pH",
            yaxis="y2",
            hovertemplate="일자 %{x}<br>평균 pH %{y:.2f}<extra></extra>",
        )
    )
    figure.update_layout(
        margin=dict(l=54, r=54, t=24, b=48),
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
        xaxis=dict(showgrid=True, gridcolor="rgba(205, 186, 166, 0.24)", zeroline=False),
        yaxis=dict(title="프레임 수", showgrid=True, gridcolor="rgba(205, 186, 166, 0.24)", zeroline=False),
        yaxis2=dict(title="평균 pH", overlaying="y", side="right", showgrid=False, zeroline=False),
        showlegend=True,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    )
    return figure


def build_main_final_inspection_button(contamination: str, is_active: bool = False, period: str = "week"):
    payload = _main_inspection_button_payload(contamination, period)
    status_class = "danger" if payload["status"] == "위험" else "warning" if payload["status"] == "경고" else ""
    class_name = "batch-preview-button active" if is_active else "batch-preview-button"

    return html.Button(
        [
            html.Div(
                [
                    html.Div(payload["line_label"], className="preview-chip"),
                    html.Div(payload["status"], className=f"preview-status {status_class}"),
                ],
                className="preview-top",
            ),
            html.Div(
                [
                    html.Div(className="qc-floor"),
                    html.Div(className="qc-path qc-path-1"),
                    html.Div(className="qc-path qc-path-2"),
                    html.Div(className="qc-unit qc-sampler"),
                    html.Div(className="qc-unit qc-lab"),
                    html.Div(className="qc-unit qc-tank"),
                    html.Div(className="qc-unit qc-droplet"),
                    html.Div(payload["focus"], className="qc-callout"),
                    html.Div(className="preview-glow"),
                ],
                className="preview-hero preview-hero-qc",
            ),
            html.Div(payload["batch_name"], className="preview-title"),
            html.Div(payload["summary"], className="preview-caption", style={"fontSize": "12px", "minHeight": "32px"}),
            html.Div([html.Span(item, className="preview-meta-pill") for item in payload["indicators"]], className="preview-meta"),
        ],
        id={"type": "main-batch-button", "index": contamination},
        n_clicks=0,
        className=class_name,
    )


def build_main_final_inspection_section(period: str = "week"):
    category_ids = get_main_inspection_category_ids(period)
    default_category = category_ids[0] if category_ids else "no"
    return html.Div(
        [
            html.Div(
                [
                    html.H2("이미지 최종검사 현황", style={"marginBottom": "18px", "fontSize": "24px", "fontWeight": "700", "color": "#1a202c"}),
                    html.P("실제 이미지 데이터셋을 5일 누적으로 집계해 정상, 화학 이상, 미생물 이상 분류를 비교합니다.", className="main-chart-description"),
                    html.Div(
                        [
                            build_main_final_inspection_button(contamination, is_active=index == 0, period=period)
                            for index, contamination in enumerate(category_ids)
                        ],
                        id="main-batch-selector",
                        className="batch-preview-strip",
                    ),
                ],
                className="main-insight-panel",
            ),
            html.Div(
                [
                    html.Div(
                        [
                            html.H2("이미지 분류 추이", style={"marginBottom": "6px", "fontSize": "24px", "fontWeight": "700", "color": "#1a202c"}),
                            html.P("선택한 분류의 일자별 검사 프레임, 출하 가능 프레임, 평균 pH를 함께 확인합니다.", className="main-chart-description"),
                        ]
                    ),
                    dcc.Graph(
                        id="main-batch-inspection-graph",
                        figure=build_main_final_inspection_figure(default_category, period),
                        config={"displayModeBar": False},
                        className="main-batch-graph",
                    ),
                ],
                className="main-insight-panel",
            ),
        ],
        className="main-insight-grid",
    )


def make_badge(text, badge_type):
    _TONE = {
        "위험":    "danger",
        "경고":    "warn",
        "정보":    "info",
        "정상":    "ok",
        "확인완료": "ok",
        "기한초과": "danger",
        "미해결":  "danger",
        "미처리":  "danger",
        "처리중":  "warn",
        "PASS":    "ok",
        "조치요망": "danger",
    }
    tone = _TONE.get(badge_type, "idle")
    return html.Div(text, className=f"ds-badge ds-badge--{tone} ds-badge--sm")


def combined_temperature_figure(selected_batch, snapshot_ratio: float | None = None):
    batch_id = int(selected_batch)
    batch_frame = _load_process_dataframe()
    batch_frame = batch_frame[batch_frame["batch_id"] == batch_id].sort_values("datetime").reset_index(drop=True)

    if batch_frame.empty:
        return go.Figure()

    if snapshot_ratio is not None:
        cutoff_index = max(1, int(len(batch_frame) * float(snapshot_ratio)))
        batch_frame = batch_frame.iloc[:cutoff_index].copy().reset_index(drop=True)

    start_time = batch_frame["datetime"].iloc[0]
    elapsed_minutes = (batch_frame["datetime"] - start_time).dt.total_seconds() / 60.0

    def _elapsed_label(total_minutes: float) -> str:
        rounded = max(0, int(round(total_minutes)))
        hours, minutes = divmod(rounded, 60)
        return f"{hours:02d}:{minutes:02d}"

    fig = go.Figure()

    stage_meta = {
        "Receiving": {
            "label": "원유입고",
            "caption": "원유 수령/검수",
            "fill": "rgba(148, 163, 184, 0.10)",
            "text": "#475569",
            "border": "rgba(148, 163, 184, 0.30)",
            "bg": "rgba(255, 255, 255, 0.92)",
        },
        "Storage": {
            "label": "저장",
            "caption": "탱크 보관",
            "fill": "rgba(59, 130, 246, 0.08)",
            "text": "#1d4ed8",
            "border": "rgba(59, 130, 246, 0.24)",
            "bg": "rgba(239, 246, 255, 0.94)",
        },
        "Filter": {
            "label": "여과",
            "caption": "이물 제거",
            "fill": "rgba(14, 165, 233, 0.08)",
            "text": "#0369a1",
            "border": "rgba(14, 165, 233, 0.22)",
            "bg": "rgba(240, 249, 255, 0.94)",
        },
        "Standardize": {
            "label": "표준화",
            "caption": "지방/고형분 조정",
            "fill": "rgba(99, 102, 241, 0.08)",
            "text": "#4338ca",
            "border": "rgba(99, 102, 241, 0.22)",
            "bg": "rgba(238, 242, 255, 0.94)",
        },
        "Heat": {
            "label": "가열",
            "caption": f"목표: {TARGET_HOLD_RANGE[0]:.0f}~{TARGET_HOLD_RANGE[1]:.0f}°C",
            "fill": "rgba(191, 124, 96, 0.16)",
            "text": "#9a3412",
            "border": "rgba(234, 88, 12, 0.28)",
            "bg": "rgba(255, 247, 237, 0.96)",
        },
        "Hold": {
            "label": "보온",
            "caption": f"유지: {TARGET_HOLD_RANGE[0]:.0f}~{TARGET_HOLD_RANGE[1]:.0f}°C",
            "fill": "rgba(250, 204, 21, 0.14)",
            "text": "#92400e",
            "border": "rgba(245, 158, 11, 0.30)",
            "bg": "rgba(255, 251, 235, 0.96)",
        },
        "Cool": {
            "label": "냉각",
            "caption": f"목표: {TARGET_COOL_MAX:.0f}°C 이하",
            "fill": "rgba(96, 165, 250, 0.18)",
            "text": "#1d4ed8",
            "border": "rgba(59, 130, 246, 0.28)",
            "bg": "rgba(239, 246, 255, 0.96)",
        },
        "Fill": {
            "label": "충진",
            "caption": "충전/포장",
            "fill": "rgba(125, 211, 252, 0.12)",
            "text": "#0369a1",
            "border": "rgba(56, 189, 248, 0.28)",
            "bg": "rgba(255, 255, 255, 0.94)",
        },
        "Inspect": {
            "label": "검사",
            "caption": "최종 품질 검사",
            "fill": "rgba(245, 158, 11, 0.10)",
            "text": "#92400e",
            "border": "rgba(245, 158, 11, 0.26)",
            "bg": "rgba(255, 251, 235, 0.96)",
        },
        "Release": {
            "label": "출하판정",
            "caption": "QA 승인/출하 결정",
            "fill": "rgba(167, 139, 250, 0.12)",
            "text": "#6d28d9",
            "border": "rgba(139, 92, 246, 0.28)",
            "bg": "rgba(245, 243, 255, 0.96)",
        },
    }

    for state_name, segment_start, segment_end in _state_segments(batch_frame):
        if state_name not in stage_meta:
            continue
        start_min = (segment_start - start_time).total_seconds() / 60.0
        end_min = (segment_end - start_time).total_seconds() / 60.0
        meta = stage_meta[state_name]
        fig.add_vrect(x0=start_min, x1=end_min, fillcolor=meta["fill"], line_width=0, layer="below")
        fig.add_annotation(
            x=(start_min + end_min) / 2,
            y=1.03,
            xref="x",
            yref="paper",
            text=f"<b>{meta['label']}</b>{f' ({meta['caption']})' if meta['caption'] else ''}",
            showarrow=False,
            font=dict(size=12, color=meta["text"]),
            bgcolor=meta["bg"],
            bordercolor=meta["border"],
            borderwidth=1,
            borderpad=6,
        )

    fig.add_trace(
        go.Scatter(
            x=elapsed_minutes,
            y=batch_frame["T"],
            mode="lines",
            line=dict(color="#64748b", width=3),
            name="온도",
            hovertemplate="경과 %{customdata}<br>온도 %{y:.2f}℃<extra></extra>",
            customdata=[_elapsed_label(value) for value in elapsed_minutes],
        )
    )

    max_elapsed = float(elapsed_minutes.iloc[-1]) if len(elapsed_minutes) else 0.0
    tick_count = min(6, max(3, int(max_elapsed // 10) + 1))
    tickvals = [round(max_elapsed * idx / max(1, tick_count - 1), 1) for idx in range(tick_count)]
    ticktext = [_elapsed_label(value) for value in tickvals]

    fig.update_layout(
        height=360,
        margin=dict(l=48, r=20, t=72, b=36),
        xaxis=dict(
            showgrid=False,
            tickvals=tickvals,
            ticktext=ticktext,
            zeroline=False,
            title="",
            tickfont=dict(size=11, color="#64748b"),
        ),
        yaxis=dict(
            gridcolor="#eef2f7",
            title="온도 (℃)",
            title_font=dict(size=13, color="#334155"),
            tickfont=dict(size=11, color="#64748b"),
            zeroline=False,
        ),
        plot_bgcolor="white",
        paper_bgcolor="white",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    )
    return fig


def radar_figure(selected_batch):
    batch_id = int(selected_batch)
    summary_row = get_batch_summary_frame().set_index("batch_id").loc[batch_id]
    categories = ["오염 위험", "살균온도", "보온시간", "pH 안정도", "점도 안정도"]
    baseline_values = [2, 2, 2, 2, 2]
    values = [
        CONTAMINATION_SCORE[summary_row["contamination"]],
        min(5, max(1, round(abs(summary_row["peak_temp"] - TARGET_HOLD_TEMP) * 2) + 1)),
        1 if summary_row["hold_time_ok"] else 5,
        min(5, max(1, round(summary_row["max_abs_ph_z"]) + 1)),
        min(5, max(1, round(summary_row["max_abs_mu_z"]) + 1)),
    ]
    fill_color = "rgba(239, 68, 68, 0.38)" if max(values) >= 4 else "rgba(245, 158, 11, 0.35)"
    line_color = "#ef4444" if max(values) >= 4 else "#f59e0b"

    fig = go.Figure()
    fig.add_trace(
        go.Scatterpolar(
            r=baseline_values,
            theta=categories,
            mode="lines",
            line=dict(color="rgba(37, 99, 235, 0.65)", width=1.5, dash="dot"),
            name="정상 기준선",
            hovertemplate="정상 기준선 %{r}<extra></extra>",
        )
    )
    fig.add_trace(
        go.Scatterpolar(
            r=values,
            theta=categories,
            fill="toself",
            fillcolor=fill_color,
            line=dict(color=line_color, width=2),
        )
    )
    fig.update_layout(
        polar={
            "radialaxis": {"visible": True, "range": [0, 5], "tickvals": [1, 2, 3, 4, 5]},
            "angularaxis": {"tickfont": {"size": 11}},
            "bgcolor": "white",
        },
        paper_bgcolor="white",
        plot_bgcolor="white",
        showlegend=False,
        margin=dict(l=40, r=40, t=20, b=20),
    )
    return fig


def _info_card(label, value):
    return html.Div(
        [
            html.Div(label, style={"fontSize": "12px", "color": "#9ca3af", "marginBottom": "5px"}),
            html.Div(value, style={"fontWeight": "700", "fontSize": "15px"}),
        ],
        style={"backgroundColor": "#f9fafb", "padding": "15px", "borderRadius": "10px", "border": "1px solid #f3f4f6"},
    )


def _bar_row(label, value_text, width, color):
    return html.Div(
        [
            html.Div(label, style={"width": "88px", "color": "#6b7280", "fontSize": "14px", "fontWeight": "700"}),
            html.Div(
                [html.Div(style={"position": "absolute", "width": width, "height": "100%", "backgroundColor": color, "borderRadius": "5px"})],
                style={"flex": 1, "height": "10px", "backgroundColor": "#e5e7eb", "borderRadius": "5px", "marginRight": "15px", "position": "relative"},
            ),
            html.Div(value_text, style={"fontWeight": "700"}),
        ],
        style={"display": "flex", "alignItems": "center", "marginBottom": "20px"},
    )


def _metric_panel(title, value, caption, accent, fill_width):
    return html.Div(
        [
            html.Div(title, style={"color": "#9ca3af", "fontSize": "13px", "marginBottom": "10px"}),
            html.Div(value, style={"color": accent, "fontWeight": "700", "fontSize": "20px", "marginBottom": "15px"}),
            html.Div(
                [html.Div(style={"width": fill_width, "height": "100%", "backgroundColor": accent, "borderRadius": "3px"})],
                style={"height": "6px", "backgroundColor": "#e5e7eb", "borderRadius": "3px", "marginBottom": "10px"},
            ),
            html.Div(caption, style={"fontSize": "12px", "color": "#9ca3af"}),
        ],
        style={"padding": "20px", "borderRadius": "10px", "border": "1px solid #f3f4f6"},
    )


def get_report_modal_children(selected_batch):
    batch_id = int(selected_batch)
    summary_row = get_batch_summary_frame().set_index("batch_id").loc[batch_id]
    date_slash = str(summary_row["date"]).replace("-", "/")
    is_pass = summary_row["status"] == "PASS"
    peak_temp = float(summary_row["peak_temp"])
    final_temp = float(summary_row["final_temp"])
    deviation_text = f"{peak_temp - TARGET_HOLD_TEMP:+.1f}℃"
    contamination_text = summary_row["contamination_label"]

    return html.Div(
        [
            html.Div(
                [
                    html.Div(
                        [
                            html.Div("살균공정 검사 보고서", style={"color": "#9ca3af", "fontSize": "13px", "fontWeight": "700", "marginBottom": "5px"}),
                            html.Div(summary_row["report_id"], style={"fontSize": "28px", "fontWeight": "800", "color": "#c2410c", "letterSpacing": "1px"}),
                            html.Div(f"익산 공장 · {date_slash} · 실배치 {summary_row['batch_name']} · LTLT 방식", style={"color": "#6b7280", "fontSize": "13px", "marginTop": "5px"}),
                        ]
                    ),
                    html.Div(
                        "CCP PASS" if is_pass else "CCP FAIL",
                        style={
                            "backgroundColor": "#dcfce7" if is_pass else "#fee2e2",
                            "color": "#166534" if is_pass else "#991b1b",
                            "padding": "10px 20px",
                            "borderRadius": "10px",
                            "fontWeight": "700",
                            "fontSize": "16px",
                            "height": "fit-content",
                        },
                    ),
                ],
                style={"display": "flex", "justifyContent": "space-between", "borderBottom": "2px solid #f3f4f6", "paddingBottom": "15px", "marginBottom": "20px"},
            ),
            html.Div("공정 기본 정보", style={"fontWeight": "700", "marginBottom": "12px", "color": "#9ca3af", "fontSize": "13px"}),
            html.Div(
                [
                    _info_card("검사 ID", summary_row["report_id"]),
                    _info_card("배치", summary_row["batch_name"]),
                    _info_card("오염 판정", contamination_text),
                    _info_card("검사 일자", date_slash),
                    _info_card("보온 상태", "정상" if summary_row["hold_time_ok"] else "이탈"),
                    _info_card("마지막 상태", STATE_LABELS.get(summary_row["last_state"], summary_row["last_state"])),
                ],
                style={"display": "grid", "gridTemplateColumns": "1fr 1fr 1fr", "gap": "15px", "marginBottom": "25px"},
            ),
            html.Div("온도 측정 결과", style={"fontWeight": "700", "marginBottom": "12px", "color": "#9ca3af", "fontSize": "13px"}),
            html.Div(
                [
                    _bar_row("CCP 목표(계획서)", "임계한계 범위", "80%", "#9ca3af"),
                    _bar_row("실제온도", f"{peak_temp:.1f}°C", f"{min(100, (peak_temp / 72.0) * 100):.1f}%", "#22c55e" if is_pass else "#ef4444"),
                    html.Div(
                        [
                            html.Span("편차", style={"width": "88px", "color": "#6b7280", "fontSize": "14px", "fontWeight": "700"}),
                            html.Span(deviation_text, style={"backgroundColor": "#dcfce7" if is_pass else "#fee2e2", "color": "#166534" if is_pass else "#991b1b", "padding": "4px 10px", "borderRadius": "5px", "fontWeight": "700"}),
                            html.Span("허용 범위: HACCP 계획서 기준", style={"fontSize": "13px", "color": "#9ca3af"}),
                        ],
                        style={"display": "flex", "alignItems": "center", "gap": "10px", "paddingTop": "20px", "borderTop": "1px dashed #e5e7eb"},
                    ),
                ],
                style={"padding": "25px", "borderRadius": "10px", "border": "1px solid #f3f4f6", "marginBottom": "25px"},
            ),
            html.Div("유지시간 및 냉각", style={"fontWeight": "700", "marginBottom": "12px", "color": "#9ca3af", "fontSize": "13px"}),
            html.Div(
                [
                    _metric_panel("유지시간", f"{summary_row['hold_minutes']:.1f}분", "기준: CCP 플래그 정상", "#22c55e" if summary_row["hold_time_ok"] else "#ef4444", "100%" if summary_row["hold_time_ok"] else "58%"),
                    _metric_panel("냉각온도", f"{final_temp:.1f}°C", "기준: 7°C 이하", "#3b82f6" if final_temp <= TARGET_COOL_MAX else "#ef4444", f"{min(100, max(12, (final_temp / 12.0) * 100)):.0f}%"),
                ],
                style={"display": "grid", "gridTemplateColumns": "1fr 1fr", "gap": "20px", "marginBottom": "25px"},
            ),
            html.Div("CCP 판정", style={"fontWeight": "700", "marginBottom": "12px", "color": "#9ca3af", "fontSize": "13px"}),
            html.Div(
                [
                    html.Div("OK" if is_pass else "!", style={"fontSize": "26px", "color": "#22c55e" if is_pass else "#ef4444", "fontWeight": "800"}),
                    html.Div(
                        [
                            html.Div("중요관리점 기준 충족" if is_pass else "중요관리점 기준 이탈", style={"color": "#166534" if is_pass else "#991b1b", "fontWeight": "700", "fontSize": "16px", "marginBottom": "5px"}),
                            html.Div(f"오염 판정 {contamination_text}, 최고온도 {peak_temp:.1f}°C, 최종 냉각온도 {final_temp:.1f}°C, 보온시간 플래그 {'정상' if summary_row['hold_time_ok'] else '이탈'}를 반영해 자동 판정했습니다.", style={"color": "#4b5563", "fontSize": "13px", "lineHeight": "1.5"}),
                        ]
                    ),
                ],
                style={"backgroundColor": "#f0fdf4" if is_pass else "#fef2f2", "padding": "20px", "borderRadius": "10px", "border": f"1px solid {'#bbf7d0' if is_pass else '#fecaca'}", "marginBottom": "25px", "display": "flex", "gap": "15px", "alignItems": "center"},
            ),
        ],
        style={"fontFamily": "sans-serif", "color": "#374151"},
    )
