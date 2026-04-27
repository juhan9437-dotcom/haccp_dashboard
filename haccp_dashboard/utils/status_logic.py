"""Unified sensor status classification for all HACCP dashboard pages.

All pages MUST import sensor_status classification from here so that
정상/경고/위험 판정 기준이 전체 대시보드에서 동일하게 유지됩니다.
"""
from __future__ import annotations

# ── 임계값 (lib.main_helpers와 동일하게 유지) ──────────────────────────────────
SIMILARITY_WARN_THRESHOLD = 0.48
SIMILARITY_DANGER_THRESHOLD = 0.75
STABILITY_WARN_THRESHOLD = 80.0
STABILITY_DANGER_THRESHOLD = 60.0

# ── 색상 체계 ──────────────────────────────────────────────────────────────────
STATUS_COLOR = {
    "정상": "#22c55e",
    "주의": "#84cc16",
    "경고": "#f59e0b",
    "위험": "#ef4444",
}
STATUS_BG = {
    "정상": "#ecfdf5",
    "주의": "#f7fee7",
    "경고": "#fffbeb",
    "위험": "#fef2f2",
}
STATUS_BORDER = {
    "정상": "#86efac",
    "주의": "#bef264",
    "경고": "#fde68a",
    "위험": "#fca5a5",
}
STATUS_TEXT = {
    "정상": "#166534",
    "주의": "#365314",
    "경고": "#b45309",
    "위험": "#991b1b",
}
STATUS_MESSAGE = {
    "정상": "정상적으로 운영 중입니다.",
    "주의": "물성 지표에서 경미한 이상징후가 감지되었습니다.",
    "경고": "공정은 진행 중이나 모니터링이 필요합니다.",
    "위험": "즉시 확인 및 조치가 필요합니다.",
}
STATUS_ACTION = {
    "정상": "정기 점검 일정을 유지하세요.",
    "주의": "물성 패턴 모니터링을 강화하고 추이를 주시하세요.",
    "경고": "물성 지표를 확인하고 오염 여부를 점검하세요.",
    "위험": "즉시 공정을 점검하고 출하를 보류하세요.",
}


def classify_sensor_status(
    top_similarity_score: float,
    stability_score: float,
    ccp_ok: bool,
) -> str:
    """통일된 센서 상태 판정.

    Parameters
    ----------
    top_similarity_score : float
        가장 높은 오염원 유사도 점수 (0~1)
    stability_score : float
        공정 안정도 점수 (0~100)
    ccp_ok : bool
        CCP 기준 충족 여부

    Returns
    -------
    str
        "위험", "경고", or "정상"
    """
    try:
        score = float(top_similarity_score)
    except (TypeError, ValueError):
        score = 0.0
    try:
        stab = float(stability_score)
    except (TypeError, ValueError):
        stab = 100.0

    if score >= SIMILARITY_DANGER_THRESHOLD or not ccp_ok:
        return "위험"
    if score >= SIMILARITY_WARN_THRESHOLD or stab < STABILITY_WARN_THRESHOLD:
        return "경고"
    return "정상"


def get_status_style(status: str) -> dict:
    """상태에 따른 스타일 딕셔너리 반환."""
    return {
        "color": STATUS_TEXT.get(status, "#374151"),
        "background": STATUS_BG.get(status, "#f8fafc"),
        "border": f"1px solid {STATUS_BORDER.get(status, '#e5e7eb')}",
    }
