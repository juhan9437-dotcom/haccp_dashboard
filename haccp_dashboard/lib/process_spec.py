"""Milk production process spec (time-based lot).

This module is intentionally lightweight so it can be imported by Dash Pages
modules at startup without pulling heavy dependencies (pandas/numpy/pandas).

전체 우유 생산 공정 흐름 (단일 패스, 8단계 거시 공정):
  계량·수유검사 → 청정 → 저유 → 균질화 → 살균 공정 → 충진 공정 → 검사 공정 → 냉장보존·출하

가열살균공정 페이지 상세 흐름 (살균 공정 내부, 6단계):
  대기(Idle) → 충진(PastFill) → 가열(HeatUp) → 살균 유지(Hold) → 냉각(Cool) → 배출(Discharge)

최종품질검사 페이지: '검사 공정' 단계 결과를 전담 (가열살균 흐름 표시 안 함)

Absolute requirements (must stay consistent across dashboard pages):
- 3 production lines (Line 1..3)
- 5 operation days
- 20 operating hours per day
- time-based lot = 2 hours (one batch)
- 3 lines * 10 lots/day/line * 5 days = 150 batches
- Each batch passes the process stages exactly once in order.
"""

from __future__ import annotations

# ── Base configuration (absolute) ──────────────────────────────────────────────
LINE_COUNT: int = 3
OPERATION_DAYS: int = 5
OPERATION_HOURS_PER_DAY: int = 20
TIME_LOT_HOURS: int = 2
DAILY_OPERATION_START_HOUR: int = 4

# ── Derived values ────────────────────────────────────────────────────────────
TIME_LOT_MINUTES: int = TIME_LOT_HOURS * 60
LOTS_PER_DAY_PER_LINE: int = int(OPERATION_HOURS_PER_DAY // TIME_LOT_HOURS)  # 10
TOTAL_BATCH_COUNT: int = int(LINE_COUNT * LOTS_PER_DAY_PER_LINE * OPERATION_DAYS)  # 150

# ── Process stages – CSV 데이터 키 (기존 호환 유지) ───────────────────────────
# 이 순서는 CSV 파일의 state 컬럼 값과 정확히 대응합니다.
PROCESS_STAGE_ORDER: list[str] = [
    "Receiving",
    "Storage",
    "Filter",
    "Standardize",
    "Heat",
    "Hold",
    "Cool",
    "Fill",
    "Inspect",
    "Release",
]

# CSV state 키 → 한국어 레이블 (state_manager, dashboard_demo 등 데이터 처리에 사용)
PROCESS_STAGE_LABELS: dict[str, str] = {
    "Receiving":   "계량·수유검사",
    "Storage":     "저유",
    "Filter":      "청정",
    "Standardize": "균질화",
    "Heat":        "가열",
    "Hold":        "살균 유지",
    "Cool":        "냉각",
    "Fill":        "충진",
    "Inspect":     "검사",
    "Release":     "출하판정",
}

# ── 전체 우유 생산 공정 (거시 8단계, UI 표시용) ──────────────────────────────
OVERALL_PROCESS_ORDER: list[str] = [
    "Receiving",     # 계량·수유검사
    "Filter",        # 청정
    "Storage",       # 저유
    "Standardize",   # 균질화
    "Pasteurize",    # 살균 공정  ← 가열살균공정 페이지 담당
    "Filling",       # 충진 공정
    "Inspect",       # 검사 공정  ← 최종품질검사 페이지 담당
    "Release",       # 냉장보존·출하
]

OVERALL_PROCESS_LABELS: dict[str, str] = {
    "Receiving":   "계량·수유검사",
    "Filter":      "청정",
    "Storage":     "저유",
    "Standardize": "균질화",
    "Pasteurize":  "살균 공정",
    "Filling":     "충진 공정",
    "Inspect":     "검사 공정",
    "Release":     "냉장보존·출하",
}

# CSV state → 거시 8단계 ID 매핑 (메인 페이지 공정 위치 표시에 사용)
OVERALL_CSV_MAP: dict[str, str] = {
    "Receiving":   "Receiving",
    "Storage":     "Storage",
    "Filter":      "Filter",
    "Standardize": "Standardize",
    "Heat":        "Pasteurize",
    "Hold":        "Pasteurize",
    "Cool":        "Pasteurize",
    "Fill":        "Filling",
    "Inspect":     "Inspect",
    "Release":     "Release",
}

# ── 가열살균공정 페이지 상세 흐름 (6단계) ────────────────────────────────────
HEATING_STAGE_ORDER: list[str] = [
    "Idle",       # 대기
    "PastFill",   # 충진 (원유 살균기 투입)
    "HeatUp",     # 가열 (72°C 도달)
    "Hold",       # 살균 유지 (CCP)
    "Cool",       # 냉각
    "Discharge",  # 배출 (충진 공정 이관)
]

HEATING_STAGE_LABELS: dict[str, str] = {
    "Idle":      "대기",
    "PastFill":  "충진",
    "HeatUp":    "가열",
    "Hold":      "살균 유지",
    "Cool":      "냉각",
    "Discharge": "배출",
}

# CSV state → 가열살균 6단계 ID 매핑
HEATING_CSV_MAP: dict[str, str] = {
    "Receiving":   "Idle",
    "Storage":     "Idle",
    "Filter":      "Idle",
    "Standardize": "PastFill",
    "Heat":        "HeatUp",
    "Hold":        "Hold",
    "Cool":        "Cool",
    "Fill":        "Discharge",
    "Inspect":     "Discharge",
    "Release":     "Discharge",
}

# ── HACCP CCP defaults (pasteurization / holding) ──────────────────────────────
CCP_HOLD_TEMP_RANGE_C: tuple[float, float] = (71.93, 72.5)
CCP_HOLD_MIN_SECONDS: int = 15
CCP_APPLICABLE_STAGES: set[str] = {"Hold", "Cool", "Fill", "Inspect", "Release"}


def validate_process_spec() -> None:
    if OPERATION_HOURS_PER_DAY % TIME_LOT_HOURS != 0:
        raise ValueError("OPERATION_HOURS_PER_DAY must be divisible by TIME_LOT_HOURS.")
    if LOTS_PER_DAY_PER_LINE != 10:
        raise ValueError(f"LOTS_PER_DAY_PER_LINE must be 10, got {LOTS_PER_DAY_PER_LINE}.")
    if TOTAL_BATCH_COUNT != 150:
        raise ValueError(f"TOTAL_BATCH_COUNT must be 150, got {TOTAL_BATCH_COUNT}.")
    if LINE_COUNT != 3:
        raise ValueError(f"LINE_COUNT must be 3, got {LINE_COUNT}.")
    if OPERATION_DAYS != 5:
        raise ValueError(f"OPERATION_DAYS must be 5, got {OPERATION_DAYS}.")
    if len(PROCESS_STAGE_ORDER) != 10:
        raise ValueError("PROCESS_STAGE_ORDER must have 10 CSV stages.")
    if set(PROCESS_STAGE_ORDER) != set(PROCESS_STAGE_LABELS):
        raise ValueError("PROCESS_STAGE_LABELS keys must match PROCESS_STAGE_ORDER.")
    if len(OVERALL_PROCESS_ORDER) != 8:
        raise ValueError("OVERALL_PROCESS_ORDER must have 8 overall stages.")
    if len(HEATING_STAGE_ORDER) != 6:
        raise ValueError("HEATING_STAGE_ORDER must have 6 heating stages.")


def process_spec_summary_ko() -> str:
    """Korean summary used across pages/reports/help text."""
    return "\n".join(
        [
            "[공정 공통 조건]",
            f"- 생산 라인: {LINE_COUNT}개 (Line 1~{LINE_COUNT})",
            f"- 운영 기간: {OPERATION_DAYS}일",
            f"- 일일 가동: {OPERATION_HOURS_PER_DAY}시간",
            f"- 배치 정의: 2시간 단위 time-based lot (= 1 batch)",
            f"- 라인당 일일 배치: {LOTS_PER_DAY_PER_LINE}개 (2시간 × {LOTS_PER_DAY_PER_LINE})",
            f"- 전체 배치: {TOTAL_BATCH_COUNT}개 (3라인 × 10배치/일 × 5일)",
            "",
            "[전체 우유 생산 공정 흐름 (단일 패스, 8단계)]",
            "계량·수유검사 → 청정 → 저유 → 균질화 → 살균 공정 → 충진 공정 → 검사 공정 → 냉장보존·출하",
            "",
            "[가열살균공정 페이지 상세 흐름 (살균 공정 내부, 6단계)]",
            "대기(Idle) → 충진(PastFill) → 가열(HeatUp) → 살균 유지(Hold) → 냉각(Cool) → 배출(Discharge)",
            "",
            "[최종품질검사 페이지]",
            "검사 공정 단계의 최종 제품 검사 결과를 표시 (가열살균 흐름 표시 안 함)",
            "",
            "[핵심 원칙]",
            "1) 배치는 시간 기반 생산 단위(2시간 lot)이다.",
            "2) 공정은 연속 흐름이지만 배치는 2시간으로 끊어 정의한다.",
            "3) 각 배치는 독립적인 품질관리 및 추적 단위이다.",
            "4) 공정 반복 ≠ 배치 반복 (배치가 하루에 여러 번 공정을 돈다는 표현 금지).",
        ]
    )


# Enforce invariants at import time (spec is an absolute requirement for this project).
validate_process_spec()
