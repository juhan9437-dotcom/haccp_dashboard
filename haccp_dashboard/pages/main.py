"""메인 대시보드 페이지 (/) – QA/QC 운영 현황

목적: 공장 전체 위험 상태와 즉시 조치가 필요한 Line/Batch 탐지
구성:
  1) 상단 KPI: 운영 라인 수, CCP 이탈 건수, 경고/위험 배치 수, 미조치 알람 수, 출하 영향 배치 수
  2) 중단: 라인별 즉시 조치 Batch 현황 카드 (가열살균공정 페이지와 동기화)
  3) 하단: 신호등형 CCP 상태 보드 + 정상/경고/위험 비율 도넛
"""

from __future__ import annotations

import dash
from dash import Input, Output, callback, dcc, html, no_update
from haccp_dashboard.utils.status_logic import (
    STATUS_COLOR as _STATUS_COLORS,
    STATUS_BG as _STATUS_BG,
    STATUS_BORDER as _STATUS_BORDER,
    STATUS_TEXT as _STATUS_TEXT,
)
from haccp_dashboard.components.status_badges import kpi_card as _kpi_card, CARD_STYLE as _CARD_STYLE

dash.register_page(__name__, path="/")

_CCP_THRESHOLD_PCT = 3.0  # 허용 기준 (%)


# mdi 아이콘 이름 → 이모지 매핑
_ICON_MAP = {
    "mdi:milk":                    "🥛",
    "mdi:alert-circle-outline":    "🛡",
    "mdi:package-variant-closed":  "📦",
    "mdi:alarm-light-outline":     "🔔",
}


def _main_kpi(label: str, value: str, sub: str = "", accent: str = "#1565c0",
              icon: str = "") -> html.Div:
    """KPI 카드 (아이콘/컬러 강조 제거 버전)."""
    return html.Div(
        [
            html.Div(label, className="ds-kpi-label"),
            html.Div(value, className="ds-kpi-value"),
            html.Div(sub, className="ds-kpi-sub") if sub else None,
        ],
        className="ds-kpi-card",
    )


def _get_rate_panel_data() -> dict:
    """최종제품검사 데이터 기반: 라인별 부적합(chem/bio) 배치 건수."""
    try:
        from haccp_dashboard.lib.dashboard_demo import get_final_inspection_summary_frame
        summary = get_final_inspection_summary_frame()
    except Exception:
        summary = None

    result = {}
    for lid in range(1, 4):
        try:
            if summary is None or summary.empty or "line_id" not in summary.columns:
                raise ValueError("no data")
            ldf = summary[summary["line_id"].astype(int) == lid]
            if ldf.empty:
                raise ValueError("empty line")
            total = 0
            devs = 0
            for _, bg in ldf.groupby("batch_id"):
                total += 1
                if bg["contamination"].isin(["chem", "bio"]).any():
                    devs += 1
            rate = round(devs / total * 100.0, 1) if total else 0.0
            level = "위험" if any(ldf["contamination"].eq("bio")) else ("경고" if devs > 0 else "정상")
            result[lid] = {"total": total, "dev": devs, "rate": rate, "level": level}
        except Exception:
            result[lid] = {"total": 0, "dev": 0, "rate": 0.0, "level": "정상"}
    return result


def _get_ccp_board_data() -> dict:
    """가열살균공정 데이터 기반: 라인별 배치 수 및 CCP 이탈(온도·유지시간) 건수."""
    try:
        from haccp_dashboard.lib.dashboard_demo import get_batch_summary_frame
        summary = get_batch_summary_frame()
    except Exception:
        summary = None

    result = {}
    for lid in range(1, 4):
        try:
            if summary is None or summary.empty or "line_id" not in summary.columns:
                raise ValueError("no data")
            ldf = summary[summary["line_id"].astype(int) == lid]
            if ldf.empty:
                raise ValueError("empty line")
            total = len(ldf)
            # hold_temp_ok 또는 hold_time_ok 가 False 인 배치 = CCP 이탈
            devs = int((~ldf["hold_temp_ok"].fillna(True) | ~ldf["hold_time_ok"].fillna(True)).sum())
            rate = round(devs / total * 100.0, 1) if total else 0.0
            if devs == 0:
                level = "정상"
            elif devs / total >= 0.5:
                level = "위험"
            else:
                level = "경고"
            result[lid] = {"total": total, "dev": devs, "rate": rate, "level": level}
        except Exception:
            result[lid] = {"total": 0, "dev": 0, "rate": 0.0, "level": "정상"}
    return result


def _build_kpi_section(_kpis=None):
    try:
        from haccp_dashboard.lib.main_helpers import (
            build_kpi_items,
            get_today_data,
            load_process_batch_dataframe,
            resolve_process_csv_path,
        )
        frame = load_process_batch_dataframe(resolve_process_csv_path())
        today_data = get_today_data(frame)
        items = build_kpi_items(today_data)
        cards = [
            _main_kpi(it["title"], it["value"], it.get("description", ""),
                      it.get("accent", "#3b82f6"))
            for it in items
        ]
    except Exception:
        cards = [
            _main_kpi("일일 총 생산량", "-", "당일 우유 생산량 집계", "#3b82f6"),
            _main_kpi("CCP 이탈 건수", "-", "CCP 기준 벳어난 공정 수", "#ef4444"),
            _main_kpi("출하영향 공정 수", "-", "출하 보류·추가 판정 공정 수", "#f97316"),
            _main_kpi("미조치 고위험 알람 수", "-", "즉시 조치 필요 알람", "#dc2626"),
        ]

    return html.Div(cards, className="ds-kpi-grid")


def _build_line_card(line_state):
    line_id    = line_state.get("line_id", 1)
    batch_name = line_state.get("batch_name", "-")
    stage_label = line_state.get("stage_label", "-")
    sensor_status = line_state.get("sensor_status", "정상")
    top_name   = line_state.get("top_name", "-")
    top_score  = line_state.get("top_score", 0.0)
    action_message = line_state.get("action_message", "-")
    T          = line_state.get("T", 0.0)
    pH         = line_state.get("pH", 0.0)
    stability  = line_state.get("stability_score", 100.0)
    ccp_ok     = line_state.get("ccp_ok", True)

    accent     = _STATUS_COLORS.get(sensor_status, "#6b7280")
    act_bg     = _STATUS_BG.get(sensor_status, "#f8fafc")
    act_text   = _STATUS_TEXT.get(sensor_status, "#374151")
    _tone      = {"정상": "ok", "경고": "warn", "위험": "danger"}.get(sensor_status, "idle")
    stab_color = "#b91c1c" if stability < 60 else "#b45309" if stability < 80 else "#15803d"
    ccp_tone   = "ok" if ccp_ok else "danger"

    metrics = html.Div(
        [
            html.Div(
                [html.Div("공정 단계", className="ds-lc-label"),
                 html.Div(stage_label, className="ds-lc-value")],
                className="ds-lc-metric",
            ),
            html.Div(className="ds-lc-divider"),
            html.Div(
                [html.Div("온도 / pH", className="ds-lc-label"),
                 html.Div(f"{T:.1f}℃ / {pH:.2f}", className="ds-lc-value")],
                className="ds-lc-metric",
            ),
            html.Div(className="ds-lc-divider"),
            html.Div(
                [html.Div("안정도", className="ds-lc-label"),
                 html.Div(f"{stability:.1f}%", className="ds-lc-value",
                          style={"color": stab_color})],
                className="ds-lc-metric",
            ),
        ],
        className="ds-lc-metrics-row",
    )

    contam_row = html.Div(
        [
            html.Div(
                [html.Div("최고 오염원 유사도", className="ds-lc-label"),
                 html.Div(
                     [html.Span(top_name, style={"fontWeight": "800", "color": accent, "fontSize": "14px"}),
                      html.Span(f" {top_score:.2f}", style={"fontSize": "12px", "color": "#6b7280"})]
                 )],
            ),
            html.Span("CCP 충족" if ccp_ok else "CCP 이탈",
                      className=f"ds-badge ds-badge--{ccp_tone} ds-badge--sm"),
        ],
        className="ds-lc-contam-row",
    )

    action_row = html.Div(
        [
            html.Div("조치 사항", className="ds-lc-label", style={"marginBottom": "6px"}),
            html.Div(
                html.Span(action_message, style={"fontSize": "12.5px", "lineHeight": "1.55",
                                                 "color": act_text}),
                className="ds-lc-action-box",
                style={"background": act_bg, "borderLeft": f"3px solid {accent}",
                       "padding": "10px 14px"},
            ),
        ],
    )

    link_row = html.Div(
        html.Button(
            "가열살균공정 상세 보기 →",
            id={"type": "line-batch-detail-btn", "index": line_id},
            n_clicks=0,
            className="ds-link-btn",
        ),
        className="ds-lc-link-row",
    )

    return html.Div(
        [
            html.Div(
                [
                    html.Div(
                        [html.Div(f"Line {line_id}", className="ds-lc-title"),
                         html.Div(batch_name, className="ds-lc-batch")],
                    ),
                    html.Span(sensor_status,
                              className=f"ds-badge ds-badge--{_tone} ds-badge--sm"),
                ],
                className="ds-lc-header",
            ),
            html.Hr(className="ds-lc-hr"),
            metrics,
            html.Hr(className="ds-lc-hr"),
            contam_row,
            html.Hr(className="ds-lc-hr"),
            action_row,
            link_row,
        ],
        className="ds-lc-card",
    )


def _build_line_cards_section(line_states):
    cards = [_build_line_card(line_states.get(i, {"line_id": i})) for i in range(1, 4)]
    return html.Div(
        [
            html.Div([
                html.H2("라인별 현재 배치 현황", className="ds-section-header"),
                html.Div("현재 생산 중인 배치의 실시간 상태입니다.",
                          className="ds-section-sub"),
            ], style={"marginBottom": "16px"}),
            html.Div(cards, className="ds-lc-grid"),
        ],
        className="ds-lc-section",
    )


def _build_ccp_board(board: dict) -> html.Div:
    from datetime import datetime
    update_time = datetime.now().strftime("%H:%M:%S")

    line_rows = []
    counts = {"위험": 0, "경고": 0, "정상": 0}
    for lid in range(1, 4):
        d = board.get(lid, {"total": 0, "dev": 0, "rate": 0.0, "level": "정상"})
        lv = d["level"]
        counts[lv] += 1
        action = "안정적 운영 중" if lv == "정상" else "모니터링 필요" if lv == "경고" else "즉시 조치 필요"
        action_icon = "✅" if lv == "정상" else "⚠️" if lv == "경고" else "🚨"
        _tone = {"정상": "ok", "경고": "warn", "위험": "danger"}.get(lv, "idle")
        line_rows.append(html.Div(
            [
                html.Div(
                    [
                        html.Div(className="ds-ccp-dot",
                                 style={"background": _STATUS_COLORS[lv]}),
                        html.Span(f"Line {lid}", className="ds-ccp-line-name"),
                        html.Span(lv, className=f"ds-badge ds-badge--{_tone} ds-badge--sm"),
                    ],
                    className="ds-ccp-row-left",
                ),
                html.Div(
                    [html.Div("CCP 이탈 건수", className="ds-ccp-stat-label"),
                     html.Div(f"{d['dev']} 건", className="ds-ccp-stat-value")],
                    className="ds-ccp-stat",
                ),
                html.Div(
                    [html.Div("이탈 비율", className="ds-ccp-stat-label"),
                     html.Div(f"{d['rate']:.1f}%", className="ds-ccp-stat-value",
                              style={"color": _STATUS_TEXT[lv] if d["dev"] > 0 else "inherit"})],
                    className="ds-ccp-stat",
                ),
                html.Div(
                    [html.Span(action_icon, style={"marginRight": "5px"}), action],
                    className="ds-ccp-action-chip",
                    style={"color": _STATUS_TEXT[lv], "background": _STATUS_BG[lv],
                           "border": f"1px solid {_STATUS_BORDER[lv]}"},
                ),
            ],
            className="ds-ccp-row",
            style={"border": f"1px solid {_STATUS_BORDER[lv]}"},
        ))

    summary_pills = html.Div(
        [
            html.Div([html.Span("●", style={"color": _STATUS_COLORS["위험"], "marginRight": "5px"}),
                      f"위험 {counts['위험']}"], className="ds-summary-pill ds-summary-pill--danger"),
            html.Div([html.Span("●", style={"color": _STATUS_COLORS["경고"], "marginRight": "5px"}),
                      f"경고 {counts['경고']}"], className="ds-summary-pill ds-summary-pill--warn"),
            html.Div([html.Span("●", style={"color": _STATUS_COLORS["정상"], "marginRight": "5px"}),
                      f"정상 {counts['정상']}"], className="ds-summary-pill ds-summary-pill--ok"),
        ],
        className="ds-pair-footer",
    )

    all_ok = counts["위험"] == 0 and counts["경고"] == 0

    return html.Div(
        [
            html.Div(
                [
                    html.Div(
                        [html.Span("라인별 실시간 CCP 상태 보드", className="ds-card-title"),
                         html.Span("실시간",
                                   className="ds-badge ds-badge--ok ds-badge--sm",
                                   style={"marginLeft": "8px"})],
                        style={"display": "flex", "alignItems": "center"},
                    ),
                    html.Div(f"🕐 {update_time}", className="ds-card-update"),
                ],
                className="ds-card-header ds-card-header--center",
                style={"marginBottom": "4px"},
            ),
            html.P("막대 그래프 대신 라인별 현재 상태를 즉시 파악할 수 있도록 신호등형 상태 보드로 표시합니다.",
                   className="ds-card-sub", style={"marginBottom": "12px"}),
            html.Div(line_rows, style={"display": "flex", "flexDirection": "column",
                                       "gap": "8px"}),
            html.Div(style={"flex": "1"}),
            summary_pills,
        ],
        style={**_CARD_STYLE, "marginBottom": "0", "height": "100%",
               "display": "flex", "flexDirection": "column",
               "borderRadius": "18px", "padding": "20px 22px"},
    )


def _build_rate_panel(board: dict) -> html.Div:
    """하단 우측: 라인별 실시간 부적합 건수 현황 (수평 바 + 건수/비율 레이블)."""
    from datetime import datetime
    update_time = datetime.now().strftime("%H:%M:%S")

    # 막대 길이 기준: 가장 많은 부적합 건수를 기준으로 정규화
    max_dev = max((board.get(i, {}).get("dev", 0) for i in range(1, 4)), default=1)
    x_max = max(max_dev, 1)

    rows = []
    for lid in range(1, 4):
        d = board.get(lid, {"total": 0, "dev": 0, "rate": 0.0, "level": "정상"})
        dev = d["dev"]
        total = d["total"]
        rate = d["rate"]
        lv = d["level"]
        bar_color = _STATUS_COLORS[lv]
        bar_pct = min(dev / x_max, 1.0) * 100.0

        # 막대 안 또는 오른쪽에 "검사 N건 중 X.X%" 레이블
        ratio_label = f"검사 {total}건 중 {rate:.1f}%" if total > 0 else "데이터 없음"

        rows.append(html.Div(
            [
                html.Div(f"Line {lid}", className="ds-rate-label"),
                html.Div(
                    [
                        html.Div(
                            html.Div(className="ds-rate-bar",
                                      style={"width": f"{bar_pct:.1f}%",
                                              "minWidth": "4px" if dev > 0 else "0",
                                              "background": bar_color}),
                            className="ds-rate-track",
                        ),
                        html.Div(ratio_label, className="ds-rate-caption"),
                    ],
                    style={"display": "flex", "alignItems": "center", "flex": "1", "minWidth": "0"},
                ),
                html.Div(f"{dev}건", className="ds-rate-count",
                          style={"color": bar_color if dev > 0 else "#9ca3af"}),
            ],
            className="ds-rate-row",
        ))

    # 합계
    total_all = sum(board.get(i, {}).get("total", 0) for i in range(1, 4))
    dev_all   = sum(board.get(i, {}).get("dev", 0)   for i in range(1, 4))
    rate_all  = round(dev_all / total_all * 100.0, 1) if total_all else 0.0

    summary = html.Div(
        [
            html.Span("전체", className="ds-card-sub"),
            html.Span(
                f"{dev_all}건 / 검사 {total_all}건 중 {rate_all:.1f}%",
                style={"fontWeight": "700",
                       "color": "#b91c1c" if dev_all > 0 else "#15803d",
                       "marginLeft": "10px"},
            ),
        ],
        className="ds-rate-summary",
    )

    return html.Div(
        [
            html.Div(
                [
                    html.Span("라인별 실시간 부적합 건수 현황", className="ds-card-title"),
                    html.Span(f"🕐 {update_time}", className="ds-card-update"),
                ],
                className="ds-card-header ds-card-header--center",
                style={"marginBottom": "4px"},
            ),
            html.P(
                "최종제품검사 완료 배치 기준 라인별 부적합(혼입) 건수 및 비율.",
                className="ds-card-sub", style={"marginBottom": "14px"},
            ),
            html.Div(rows, style={"display": "flex", "flexDirection": "column",
                                   "gap": "18px"}),
            html.Div(style={"flex": "1"}),
            summary,
        ],
        style={**_CARD_STYLE, "marginBottom": "0", "height": "100%",
               "display": "flex", "flexDirection": "column",
               "borderRadius": "18px", "padding": "20px 22px"},
    )


# ── 레이아웃 ───────────────────────────────────────────────────────────────────

def layout(**_kwargs):
    return html.Div(
        [
            html.Div(
                [
                    html.H1("QA/QC 운영 현황", className="ds-page-title",
                            style={"marginBottom": "4px"}),
                    html.Div("전 공장 실시간 품질 현황 모니터링",
                             className="ds-page-subtitle"),
                ],
                style={"marginBottom": "4px"},
            ),
            html.Div(id="main-dashboard-content", children=_build_initial_content()),
            dcc.Interval(id="main-refresh-interval", interval=30_000, n_intervals=0),
        ],
        style={"minWidth": "0", "padding": "4px 0"},
    )


def _build_initial_content():
    try:
        from haccp_dashboard.utils.state_manager import get_per_line_states
        line_states = get_per_line_states()
    except Exception:
        line_states = {}
    board_data = _get_ccp_board_data()
    rate_data = _get_rate_panel_data()
    bottom_grid = html.Div(
        [_build_ccp_board(board_data), _build_rate_panel(rate_data)],
        style={"display": "grid", "gridTemplateColumns": "1fr 1fr",
               "gap": "20px", "alignItems": "stretch", "marginTop": "24px"},
    )
    return [
        _build_kpi_section(),
        _build_line_cards_section(line_states),
        bottom_grid,
    ]


# ── 콜백: 주기적 갱신 ──────────────────────────────────────────────────────────

@callback(
    Output("main-dashboard-content", "children"),
    Input("main-refresh-interval", "n_intervals"),
    Input("sensor-cache", "data"),
)
def refresh_main_dashboard(_n, _sensor_cache):
    return _build_initial_content()


@callback(
    Output("heating-selected-batch-store", "data"),
    Output("url", "pathname"),
    Input({"type": "line-batch-detail-btn", "index": dash.ALL}, "n_clicks"),
    prevent_initial_call=True,
)
def _navigate_to_heating_with_batch(n_clicks_list):
    if not any(n_clicks_list or []):
        return no_update, no_update
    from dash import ctx
    triggered = ctx.triggered_id
    if not triggered:
        return no_update, no_update
    line_id = int(triggered["index"])
    try:
        from haccp_dashboard.utils.state_manager import get_per_line_states
        states = get_per_line_states()
        batch_id = states.get(line_id, {}).get("batch_id")
        if batch_id is None:
            return no_update, "/heating"
        return {"batch_id": int(batch_id), "line_id": line_id}, "/heating"
    except Exception:
        return no_update, "/heating"
