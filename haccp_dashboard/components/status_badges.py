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


# ── KPI 카드 (전 페이지 공통 컴포넌트) ────────────────────────────────────────
#
# 디자인 규칙(고정):
#   - 카드: ds-kpi-card 단일 클래스만 사용 (--sm, borderLeftColor 등 변형 금지)
#   - 내부: 상단 제목(ds-kpi-label) / 중단 수치(ds-kpi-value) / 하단 설명(ds-kpi-sub)
#   - 좌측 정렬, 동일한 폰트/여백/높이
#   - 아이콘·배지·배경색·컬러 강조 없음
# 다른 페이지에서도 제목/숫자/설명만 바뀌고 디자인은 100% 동일해야 한다.
# ----------------------------------------------------------------------------

def kpi_card(
    title: str,
    value: str,
    description: str = "",
    accent: str | None = None,   # (호환용) 무시됨 - 색 강조 금지
    status: str | None = None,   # (호환용) 무시됨
    **_legacy,                   # is_main, icon, sub 등 구버전 인자 흡수
) -> html.Div:
    """전 페이지 공통 KPI 카드.

    Args:
        title: 카드 제목 (예: "일일 총 생산량")
        value: 핵심 수치 + 단위 (예: "10,230 L", "0", "24")
        description: 1~2줄 짧은 설명 (선택)
    """
    children = [
        html.Div(title, className="ds-kpi-label"),
        html.Div(value, className="ds-kpi-value"),
    ]
    if description:
        children.append(html.Div(description, className="ds-kpi-sub"))
    return html.Div(children, className="ds-kpi-card")


def kpi_row(cards: list) -> html.Div:
    """KPI 카드들을 동일 간격·동일 높이로 가로 배치한다."""
    return html.Div(cards, className="ds-kpi-grid")


# 별칭 — 페이지에서 의미가 명확하도록
create_kpi_card = kpi_card
create_kpi_grid = kpi_row


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
