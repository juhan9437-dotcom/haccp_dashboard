"""공통 UI 컴포넌트 – 상태 배지 및 KPI 카드.

모든 페이지에서 동일한 스타일의 상태 표시와 KPI 카드를 사용하기 위한 모듈입니다.
"""
from __future__ import annotations

from dash import html
from haccp_dashboard.utils.status_logic import STATUS_COLOR

# 공통 카드 스타일 – DS 토큰에 맞춰 정렬
# 레거시 spread(style={**_CARD_STYLE, ...})와 계속 호환됨
CARD_STYLE: dict = {
    "background": "#ffffff",
    "border": "1px solid #dde3ec",
    "borderRadius": "12px",
    "padding": "20px 24px",
    "marginBottom": "16px",
    "boxShadow": "0 1px 4px rgba(13,27,42,0.06),0 4px 14px rgba(13,27,42,0.05)",
}


# ── 상태 배지 ──────────────────────────────────────────────────────────────────

# 배지 tone 매핑 (label → DS tone class)
_TONE_MAP: dict = {
    "정상":    "ok",
    "PASS":    "ok",
    "확인완료": "ok",
    "경고":    "warn",
    "처리중":  "warn",
    "위험":    "danger",
    "조치요망": "danger",
    "미해결":  "danger",
    "미처리":  "danger",
    "기한초과": "danger",
    "검사 대기": "idle",
    "대기":    "idle",
    "정보":    "info",
}


def status_badge(label: str, size: str = "sm") -> html.Span:
    """상태 배지 컴포넌트를 반환합니다."""
    tone = _TONE_MAP.get(label, "idle")
    size_cls = "ds-badge--sm" if size == "sm" else "ds-badge--md"
    return html.Span(label, className=f"ds-badge ds-badge--{tone} {size_cls}")


def status_dot(status: str) -> html.Span:
    """작은 상태 점(dot)을 반환합니다."""
    color = STATUS_COLOR.get(status, "#94a3b8")  # noqa: kept for callers
    return html.Span(
        "",
        style={
            "display": "inline-block",
            "width": "10px",
            "height": "10px",
            "borderRadius": "50%",
            "background": color,
            "marginRight": "6px",
            "verticalAlign": "middle",
        },
    )


# ── KPI 카드 ───────────────────────────────────────────────────────────────────

def kpi_card(
    title: str,
    value: str,
    description: str = "",
    accent: str = "#1565c0",
    status: str | None = None,
) -> html.Div:
    """상태 KPI 카드를 반환합니다."""
    if status == "위험":
        accent = "#b91c1c"
    elif status == "경고":
        accent = "#b45309"
    elif status == "정상":
        accent = "#15803d"

    return html.Div(
        [
            html.Div(title, className="ds-kpi-label"),
            html.Div(value, className="ds-kpi-value", style={"color": accent}),
            html.Div(description, className="ds-kpi-sub") if description else None,
        ],
        className="ds-kpi-card",
        style={"borderLeftColor": accent},
    )


def kpi_row(cards: list) -> html.Div:
    """KPI 카드들을 가로로 배치합니다."""
    return html.Div(cards, className="ds-kpi-grid")


# ── 섹션 헤더 ──────────────────────────────────────────────────────────────────

def section_header(title: str, subtitle: str = "", action_btn=None) -> html.Div:
    """섹션 헤더 컴포넌트를 반환합니다."""
    return html.Div(
        [
            html.Div([
                html.H2(title, className="ds-section-header"),
                html.Div(subtitle, className="ds-section-sub") if subtitle else None,
            ]),
            action_btn if action_btn else None,
        ],
        style={"display": "flex", "justifyContent": "space-between",
               "alignItems": "flex-start", "marginBottom": "12px"},
    )


# ── 카드 컨테이너 ──────────────────────────────────────────────────────────────

def card(children, padding: str = "20px 24px", style: dict | None = None) -> html.Div:
    """기본 카드 컨테이너를 반환합니다."""
    base_style = {
        "background": "#ffffff",
        "border": "1px solid #dde3ec",
        "borderRadius": "12px",
        "padding": padding,
        "marginBottom": "16px",
        "boxShadow": "0 1px 4px rgba(13,27,42,0.06),0 4px 14px rgba(13,27,42,0.05)",
    }
    if style:
        base_style.update(style)
    return html.Div(children, style=base_style)
