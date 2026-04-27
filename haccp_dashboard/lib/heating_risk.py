from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

RiskLevel = str  # "정상" | "경고" | "위험"

# 가열살균(Heating) 공정 센서 기반 4단계 분류 기준
# ─────────────────────────────────────────────────────────────────────────────
# - "위험": 핵심 CCP 이탈  →  살균 온도(ccp_hold_temp_ok) 또는 유지시간(ccp_hold_time_ok) 기준 이탈
# - "경고": pH · Kappa(Tau_z) · 점도(Mu_z) 중 하나 이상이 명확히 정상 패턴 이탈  (z ≥ 2.0)
# - "주의": 위 물성 지표 중 하나 이상이 정상 범위 근처에서 이상징후  (1.0 ≤ z < 2.0)
# - "정상": CCP 충족 + 물성 지표 모두 정상 패턴 내
#
# 온도(T_z)는 CCP 플래그(ccp_hold_temp_ok)로 처리 → 물성 모니터링 대상에서 제외
HEATING_CAUTION_Z_ABS = 1.0     # 주의 임계값: 정상 패턴 대비 약한 이상징후
HEATING_WARNING_Z_ABS = 2.0     # 경고 임계값: 물성 명확한 정상 범위 이탈
HEATING_DANGER_Z_ABS = 3.0      # 극단값 참고 기준 (backward-compat)

# 물성 모니터링 대상 컬럼 – pH, Kappa(Tau_z), 점도(Mu_z)
# T_z는 CCP 플래그로 처리 → 물성 판정에서 제외
HEATING_PROPERTY_Z_COLUMNS: tuple[str, ...] = ("pH_z", "Mu_z", "Tau_z")
HEATING_Z_COLUMNS: tuple[str, ...] = ("T_z", "pH_z", "Mu_z", "Tau_z")


def _safe_float(value: Any, default: float | None = None) -> float | None:
    try:
        if value in (None, "", "None"):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _bool_or_none(value: Any) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(int(value))
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "y", "ok", "pass", "on"}:
        return True
    if text in {"0", "false", "no", "n", "fail", "off"}:
        return False
    return None


def extract_heating_z_values(row: Mapping[str, Any]) -> dict[str, float | None]:
    # 다양한 API 스키마를 흡수 (sensor-data / embedded bridge / demo)
    return {
        "T_z": _safe_float(row.get("T_z") or row.get("temp_z") or row.get("temperature_z")),
        "pH_z": _safe_float(row.get("pH_z") or row.get("ph_z")),
        "Mu_z": _safe_float(row.get("Mu_z") or row.get("mu_z") or row.get("density_z")),
        "Tau_z": _safe_float(row.get("Tau_z") or row.get("tau_z")),
    }


def _split_metrics_by_threshold(
    z_values: Mapping[str, float | None],
    *,
    warning_z: float = HEATING_WARNING_Z_ABS,
    danger_z: float = HEATING_DANGER_Z_ABS,
) -> tuple[list[str], list[str], float | None]:
    danger_metrics: list[str] = []
    warning_metrics: list[str] = []
    max_abs: float | None = None
    for name, value in z_values.items():
        if value is None:
            continue
        abs_value = abs(float(value))
        max_abs = abs_value if max_abs is None else max(max_abs, abs_value)
        if abs_value >= danger_z:
            danger_metrics.append(name)
        elif abs_value >= warning_z:
            warning_metrics.append(name)
    return danger_metrics, warning_metrics, max_abs


@dataclass(frozen=True)
class HeatingRiskDecision:
    level: RiskLevel          # "정상" | "주의" | "경고" | "위험"
    ccp_ok: bool | None
    normal_range_ok: bool | None   # property z < WARNING (backward-compat)
    stability_ok: bool | None      # property z < CAUTION (backward-compat)
    max_abs_z: float | None
    danger_metrics: list[str]      # backward-compat (위험은 CCP만 → 항상 [])
    warning_metrics: list[str]     # property metrics with z ≥ WARNING_Z (→ 경고)
    caution_metrics: list[str]     # property metrics with 1.0 ≤ z < 2.0 (→ 주의)


def classify_heating_sensor_row(
    row: Mapping[str, Any],
    *,
    warning_z: float = HEATING_WARNING_Z_ABS,
    danger_z: float = HEATING_DANGER_Z_ABS,
) -> HeatingRiskDecision:
    hold_temp_ok = _bool_or_none(row.get("ccp_hold_temp_ok"))
    hold_time_ok = _bool_or_none(row.get("ccp_hold_time_ok"))
    if hold_temp_ok is None and hold_time_ok is None:
        ccp_ok: bool | None = None
    else:
        ccp_ok = bool(hold_temp_ok is not False and hold_time_ok is not False)

    z_values = extract_heating_z_values(row)

    # 전체 z-score 통계 (max_abs_z 참고용 / backward-compat)
    _, _, max_abs_z = _split_metrics_by_threshold(z_values, warning_z=warning_z, danger_z=danger_z)

    # 물성 모니터링: pH_z, Mu_z, Tau_z만 (T_z는 CCP 플래그로 처리)
    prop_warning_metrics: list[str] = [
        name for name, v in z_values.items()
        if name in HEATING_PROPERTY_Z_COLUMNS and v is not None
        and abs(float(v)) >= HEATING_WARNING_Z_ABS
    ]
    prop_caution_metrics: list[str] = [
        name for name, v in z_values.items()
        if name in HEATING_PROPERTY_Z_COLUMNS and v is not None
        and HEATING_CAUTION_Z_ABS <= abs(float(v)) < HEATING_WARNING_Z_ABS
    ]

    # backward-compat fields
    normal_range_ok: bool | None = (len(prop_warning_metrics) == 0) if max_abs_z is not None else None
    stability_ok: bool | None = (
        len(prop_warning_metrics) == 0 and len(prop_caution_metrics) == 0
    ) if max_abs_z is not None else None

    # 4단계 판정 (주의 단계는 정상으로 통합)
    if ccp_ok is False:
        level: RiskLevel = "위험"
    elif prop_warning_metrics:
        level = "경고"
    else:
        level = "정상"

    return HeatingRiskDecision(
        level=level,
        ccp_ok=ccp_ok,
        normal_range_ok=normal_range_ok,
        stability_ok=stability_ok,
        max_abs_z=max_abs_z,
        danger_metrics=[],           # 위험은 CCP만 → property danger 미사용
        warning_metrics=prop_warning_metrics,
        caution_metrics=prop_caution_metrics,
    )

