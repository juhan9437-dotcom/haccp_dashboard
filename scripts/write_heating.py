"""Script to write the new heating.py page."""
import os

new_content = '''\
"""가열살균 공정 관리 페이지 (/heating)

목적: QA/QC 담당자가 배치별 살균공정의 위험도를 판단하고 CCP 이탈 여부를 즉시 확인
"""
from __future__ import annotations
import dash
from dash import Input, Output, State, callback, dcc, html, no_update

dash.register_page(__name__, path="/heating")

_DEFAULT_PERIOD = "week"

_CARD_STYLE = {
    "background": "white", "border": "1px solid #e5e7eb", "borderRadius": "14px",
    "padding": "18px 20px", "marginBottom": "16px",
}
_STATUS_COLORS = {"정상": "#22c55e", "경고": "#f59e0b", "위험": "#ef4444"}
_STATUS_BG = {"정상": "#ecfdf5", "경고": "#fffbeb", "위험": "#fef2f2"}
_STATUS_TEXT = {"정상": "#166534", "경고": "#b45309", "위험": "#991b1b"}


def _small_kpi(label, value, sub="", accent="#3b82f6"):
    return html.Div([
        html.Div(label, style={"fontSize": "11px", "color": "#6b7280", "fontWeight": "600", "marginBottom": "4px"}),
        html.Div(value, style={"fontSize": "22px", "fontWeight": "900", "color": accent, "lineHeight": "1.1"}),
        html.Div(sub, style={"fontSize": "10px", "color": "#9ca3af", "marginTop": "2px"}) if sub else None,
    ], style={
        "background": "white", "border": "1px solid #e5e7eb", "borderRadius": "10px",
        "padding": "12px 14px", "borderLeft": f"3px solid {accent}", "flex": "1", "minWidth": "100px",
    })


def _build_realtime_kpi_section(line_id: int = 1):
    """선택된 라인의 현재 배치 8-KPI 카드."""
    try:
        from haccp_dashboard.utils.state_manager import get_per_line_states
        states = get_per_line_states()
        s = states.get(line_id, {})
    except Exception:
        s = {}

    batch_name = s.get("batch_name", "-")
    stage_label = s.get("stage_label", "-")
    T = s.get("T", 0.0)
    pH = s.get("pH", 0.0)
    hold_min = s.get("hold_minutes", 0.0)
    ccp_ok = s.get("ccp_ok", True)
    sensor_status = s.get("sensor_status", "정상")
    stability = s.get("stability_score", 100.0)
    top_name = s.get("top_name", "-")
    top_score = s.get("top_score", 0.0)

    status_color = _STATUS_COLORS.get(sensor_status, "#6b7280")
    stab_color = "#ef4444" if stability < 60 else "#f59e0b" if stability < 80 else "#22c55e"

    kpis = [
        _small_kpi("현재 공정 단계", stage_label, "살균 공정", "#6366f1"),
        _small_kpi("현재 배치", batch_name, f"Line {line_id}", "#0ea5e9"),
        _small_kpi("목표 온도", "72.0°C", "CCP 기준", "#64748b"),
        _small_kpi("현재 온도 / pH", f"{T:.1f}°C / {pH:.2f}", "실시간 센서", "#f97316"),
        _small_kpi("보온 시간", f"{hold_min:.0f}분", "CCP ≥ 0.25분", "#8b5cf6"),
        _small_kpi("CCP 충족", "충족" if ccp_ok else "이탈", "온도x시간", "#22c55e" if ccp_ok else "#ef4444"),
        _small_kpi("센서 상태", sensor_status, f"{top_name} {top_score:.2f}", status_color),
        _small_kpi("공정 안정도", f"{stability:.1f}%", "기준 >= 80%", stab_color),
    ]

    return html.Div([
        html.Div([
            html.H2(f"Line {line_id} 현재 배치 현황", style={"fontSize": "14px", "fontWeight": "800", "color": "#111827", "margin": "0"}),
            html.Div("실시간 센서 기반 KPI", style={"fontSize": "11px", "color": "#6b7280", "marginTop": "2px"}),
        ], style={"marginBottom": "12px"}),
        html.Div(kpis, style={"display": "flex", "gap": "10px", "flexWrap": "wrap"}),
    ], style={**_CARD_STYLE, "borderTop": f"4px solid {status_color}"})


def _similarity_polygon_figure(similarity_scores: dict, stage: str = "Hold"):
    import math
    import plotly.graph_objects as go
    STAGE_COLORS = {
        "HeatUp": ("rgba(249,115,22,0.45)", "#ea580c"),
        "Hold": ("rgba(245,158,11,0.40)", "#d97706"),
        "Cool": ("rgba(96,165,250,0.40)", "#2563eb"),
    }
    fill_color, line_color = STAGE_COLORS.get(stage, ("rgba(99,102,241,0.38)", "#6366f1"))
    names = list(similarity_scores.keys())
    values = [float(v) for v in similarity_scores.values()]
    n = len(names)
    if n == 0:
        return go.Figure()
    angles = [math.tau * i / n for i in range(n)]
    x_outer = [math.cos(a) for a in angles] + [math.cos(angles[0])]
    y_outer = [math.sin(a) for a in angles] + [math.sin(angles[0])]
    x_vals = [v * math.cos(a) for v, a in zip(values, angles)] + [values[0] * math.cos(angles[0])]
    y_vals = [v * math.sin(a) for v, a in zip(values, angles)] + [values[0] * math.sin(angles[0])]
    x_half = [0.5 * math.cos(a) for a in angles] + [0.5 * math.cos(angles[0])]
    y_half = [0.5 * math.sin(a) for a in angles] + [0.5 * math.sin(angles[0])]
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=x_outer, y=y_outer, mode="lines",
                             line=dict(color="rgba(148,163,184,0.30)", width=1), hoverinfo="skip", showlegend=False))
    fig.add_trace(go.Scatter(x=x_half, y=y_half, mode="lines",
                             line=dict(color="rgba(37,99,235,0.50)", width=1, dash="dot"),
                             hoverinfo="skip", showlegend=False, name="정상 범위"))
    fig.add_trace(go.Scatter(
        x=x_vals, y=y_vals, mode="lines+markers", fill="toself",
        fillcolor=fill_color, line=dict(color=line_color, width=2),
        marker=dict(size=8, color=line_color), name="유사도",
        hovertemplate="%{text}: %{customdata:.2f}<extra></extra>",
        text=names + [names[0]], customdata=values + [values[0]],
    ))
    for name, val, angle in zip(names, values, angles):
        r = 1.18
        fig.add_annotation(
            x=r * math.cos(angle), y=r * math.sin(angle),
            text=f"<b>{name}</b><br><span style=\\'font-size:10px\\'>{val:.2f}</span>",
            showarrow=False, font=dict(size=10, color="#334155"), align="center",
        )
    fig.update_layout(
        height=280, margin=dict(l=40, r=40, t=20, b=20),
        xaxis=dict(visible=False, range=[-1.5, 1.5]),
        yaxis=dict(visible=False, range=[-1.5, 1.5], scaleanchor="x"),
        plot_bgcolor="white", paper_bgcolor="white", showlegend=False,
    )
    return fig


def _build_analysis_payload(batch_id: int) -> dict:
    try:
        from haccp_dashboard.lib.dashboard_demo import get_batch_summary_frame
        from haccp_dashboard.lib.main_helpers import (
            contaminant_scores_from_summary, classify_batch_status, _infer_stage_from_state,
        )
        summary_frame = get_batch_summary_frame()
        if summary_frame.empty or batch_id not in summary_frame["batch_id"].values:
            return {}
        row = summary_frame[summary_frame["batch_id"] == batch_id].iloc[0]
        stage = _infer_stage_from_state(row.get("last_state"))
        scores = contaminant_scores_from_summary(row, stage)
        top_name, top_score = max(scores.items(), key=lambda kv: kv[1])
        ccp_risk = 0.0 if (bool(row.get("hold_time_ok", True)) and bool(row.get("hold_temp_ok", True))) else 1.0
        level, message, action = classify_batch_status(ccp_risk, top_score, float(row.get("stability_score", 100.0)))
        ph = float(row.get("final_ph", 6.7))
        peak_t = float(row.get("peak_temp", 64.0))
        final_t = float(row.get("final_temp", 7.0))
        hold_m = float(row.get("hold_minutes", 15.0))
        sensor_reasons = []
        if abs(ph - 6.7) > 0.1:
            sensor_reasons.append(f"pH {ph:.2f} – 기준(6.6~6.8) 이탈")
        if not bool(row.get("hold_temp_ok", True)):
            sensor_reasons.append(f"살균 온도 {peak_t:.1f}C – CCP 한계 위반")
        if not bool(row.get("hold_time_ok", True)):
            sensor_reasons.append(f"보온 시간 {hold_m:.0f}분 – CCP 한계 미달")
        if final_t > 7.0:
            sensor_reasons.append(f"냉각 최종온도 {final_t:.1f}C – 7C 초과")
        return {
            "similarity_scores": scores, "top_name": top_name, "top_score": float(top_score),
            "stage": stage, "judgement": level, "message": message, "action": action,
            "sensor_reasons": sensor_reasons, "batch_name": str(row.get("batch_name", "")),
            "peak_temp": peak_t, "final_temp": final_t, "final_ph": ph, "hold_minutes": hold_m,
            "stability_score": float(row.get("stability_score", 100.0)),
            "hold_time_ok": bool(row.get("hold_time_ok", True)),
            "hold_temp_ok": bool(row.get("hold_temp_ok", True)),
        }
    except Exception:
        return {}


def _build_process_flow_col(payload: dict):
    if not payload:
        return html.Div("데이터 없음", style={"color": "#94a3b8", "padding": "20px"})
    stage = payload.get("stage", "Hold")
    batch_name = payload.get("batch_name", "-")
    peak_t = payload.get("peak_temp", 0.0)
    final_ph = payload.get("final_ph", 0.0)
    hold_m = payload.get("hold_minutes", 0.0)
    hold_time_ok = payload.get("hold_time_ok", True)
    hold_temp_ok = payload.get("hold_temp_ok", True)
    stage_order = ["HeatUp", "Hold", "Cool"]
    stage_labels = {"HeatUp": "가열 단계", "Hold": "보온(CCP) 단계", "Cool": "냉각 단계"}
    stage_descs = {
        "HeatUp": f"목표 72C 도달 · 현재 최고 {peak_t:.1f}C",
        "Hold": f"보온 시간 {hold_m:.0f}분 · {'CCP 충족' if hold_time_ok and hold_temp_ok else 'CCP 이탈'}",
        "Cool": f"최종 pH {final_ph:.2f} · 냉각 완료",
    }
    stage_nodes = []
    for st in stage_order:
        is_current = (st == stage)
        is_done = stage_order.index(st) < stage_order.index(stage)
        node_color = "#3b82f6" if is_current else "#22c55e" if is_done else "#e5e7eb"
        border = "3px solid #1d4ed8" if is_current else f"1px solid {node_color}"
        stage_nodes.append(html.Div([
            html.Div(style={"width": "10px", "height": "10px", "borderRadius": "50%",
                            "background": node_color, "marginRight": "10px", "flexShrink": "0"}),
            html.Div([
                html.Div(stage_labels[st], style={"fontSize": "12px", "fontWeight": "700",
                                                   "color": "#1f2937" if (is_current or is_done) else "#9ca3af"}),
                html.Div(stage_descs[st], style={"fontSize": "10px", "color": "#6b7280", "marginTop": "2px"}),
            ]),
        ], style={"display": "flex", "alignItems": "center", "padding": "10px 12px",
                  "borderRadius": "8px", "background": "#eff6ff" if is_current else "#f9fafb",
                  "border": border, "marginBottom": "8px"}))
    return html.Div([
        html.Div("공정 흐름", style={"fontSize": "13px", "fontWeight": "800", "color": "#374151", "marginBottom": "12px"}),
        html.Div(f"배치: {batch_name}", style={"fontSize": "11px", "color": "#6b7280", "marginBottom": "10px"}),
        *stage_nodes,
        html.Div(f"현재 단계: {stage_labels.get(stage, stage)}", style={
            "marginTop": "10px", "fontSize": "11px", "fontWeight": "700",
            "color": "#3b82f6", "background": "#eff6ff", "padding": "6px 10px",
            "borderRadius": "6px", "textAlign": "center",
        }),
    ])


def _build_similarity_col(payload: dict):
    if not payload:
        return html.Div("데이터 없음", style={"color": "#94a3b8", "padding": "20px"})
    scores = payload.get("similarity_scores", {})
    stage = payload.get("stage", "Hold")
    top_name = payload.get("top_name", "-")
    top_score = payload.get("top_score", 0.0)
    fig = _similarity_polygon_figure(scores, stage)
    return html.Div([
        html.Div("오염 유사도 분석", style={"fontSize": "13px", "fontWeight": "800", "color": "#374151", "marginBottom": "8px"}),
        html.Div(f"분석 단계: {stage}", style={"fontSize": "11px", "color": "#6b7280", "marginBottom": "8px"}),
        dcc.Graph(figure=fig, config={"displayModeBar": False}),
        html.Div([
            html.Div("최근접 오염원", style={"fontSize": "10px", "color": "#94a3b8", "marginBottom": "2px"}),
            html.Span(f"{top_name}  ", style={"fontSize": "15px", "fontWeight": "900", "color": "#0f172a"}),
            html.Span(f"{top_score:.2f}", style={"fontSize": "13px", "color": "#6b7280"}),
        ]),
    ])


def _build_ai_summary_col(payload: dict):
    if not payload:
        return html.Div("데이터 없음", style={"color": "#94a3b8", "padding": "20px"})
    level = payload.get("judgement", "정상")
    message = payload.get("message", "")
    action = payload.get("action", "")
    reasons = payload.get("sensor_reasons", [])
    level_colors = {
        "정상": ("#ecfdf5", "#166534", "#22c55e"),
        "경고": ("#fffbeb", "#b45309", "#f59e0b"),
        "위험": ("#fef2f2", "#991b1b", "#ef4444"),
    }
    bg, fg, border_c = level_colors.get(level, ("#f8fafc", "#374151", "#94a3b8"))
    return html.Div([
        html.Div("AI 판정 요약", style={"fontSize": "13px", "fontWeight": "800", "color": "#374151", "marginBottom": "12px"}),
        html.Div([
            html.Div(f"판정: {level}", style={"fontSize": "18px", "fontWeight": "900", "color": fg, "marginBottom": "6px"}),
            html.Div(message, style={"fontSize": "12px", "color": fg, "lineHeight": "1.5"}),
        ], style={"background": bg, "border": f"1px solid {border_c}30",
                  "borderLeft": f"4px solid {border_c}",
                  "borderRadius": "10px", "padding": "12px 14px", "marginBottom": "12px"}),
        html.Div([
            html.Div("권고 조치", style={"fontSize": "11px", "color": "#94a3b8", "marginBottom": "4px"}),
            html.Div(action, style={"fontSize": "12px", "color": "#374151", "fontWeight": "600", "lineHeight": "1.5"}),
        ], style={"marginBottom": "14px"}),
        html.Div([
            html.Div("이상 감지 항목", style={"fontSize": "11px", "color": "#94a3b8", "fontWeight": "700", "marginBottom": "6px"}),
            *([html.Div(r, style={"fontSize": "11px", "color": "#374151", "padding": "4px 8px",
                                   "background": "#fef9c3", "borderRadius": "4px", "marginBottom": "4px"})
               for r in reasons] if reasons else [
                html.Div("이상 없음", style={"fontSize": "11px", "color": "#22c55e", "fontWeight": "600"})
            ]),
        ]),
    ])


def _make_badge(text: str, tone: str):
    try:
        from haccp_dashboard.lib.dashboard_demo import make_badge
        return make_badge(text, tone)
    except Exception:
        return html.Span(text, style={"fontSize": "11px", "fontWeight": "700"})


def _build_report_table(rows: list):
    if not rows:
        return html.Div("표시할 배치 데이터가 없습니다.",
                        style={"color": "#64748b", "padding": "24px", "textAlign": "center", "fontSize": "14px"})
    header = html.Thead(html.Tr(
        [html.Th(h, style={"padding": "10px 8px", "fontSize": "12px"}) for h in
         ["배치", "이름", "일자", "오염 판정", "최고 온도", "편차", "보온 시간", "안정도", "상태", "상세"]],
        style={"color": "#6b7280", "borderBottom": "1px solid #e5e7eb", "background": "#f9fafb"},
    ))

    def _row(r):
        deviation = r.get("deviation", 0.0)
        dev_color = "#ef4444" if abs(deviation) > 1.5 else "#f59e0b" if abs(deviation) > 0.5 else "#22c55e"
        stability = r.get("stability_score", 0.0)
        stab_color = "#ef4444" if stability < 60 else "#f59e0b" if stability < 80 else "#22c55e"
        return html.Tr([
            html.Td(str(r.get("batch_id", "")), style={"padding": "12px 8px", "fontSize": "12px"}),
            html.Td(r.get("batch_name", ""), style={"fontSize": "12px"}),
            html.Td(r.get("date", ""), style={"fontSize": "12px"}),
            html.Td(_make_badge(r.get("contamination_label", ""), r.get("contamination_badge", "")),
                    style={"padding": "10px 0"}),
            html.Td(f"{r.get('peak_temp', 0.0):.1f}C", style={"fontSize": "12px"}),
            html.Td(f"{deviation:+.1f}C", style={"fontSize": "12px", "color": dev_color, "fontWeight": "700"}),
            html.Td(f"{r.get('hold_minutes', 0.0):.0f}분", style={"fontSize": "12px"}),
            html.Td(f"{stability:.1f}%", style={"fontSize": "12px", "color": stab_color, "fontWeight": "700"}),
            html.Td(_make_badge(r.get("status", ""), r.get("status", "")), style={"padding": "10px 0"}),
            html.Td(html.Button(
                "분석 보기",
                id={"type": "heating-batch-btn", "index": r.get("batch_id", 0)},
                n_clicks=0,
                style={"background": "#eff6ff", "border": "1px solid #bfdbfe", "borderRadius": "8px",
                       "padding": "5px 10px", "fontSize": "11px", "cursor": "pointer",
                       "color": "#1d4ed8", "fontWeight": "600"},
            )),
        ], style={"borderBottom": "1px solid #f3f4f6"})

    return html.Table([header, html.Tbody([_row(r) for r in rows])],
                      style={"width": "100%", "textAlign": "center", "fontSize": "12px", "tableLayout": "fixed"})


def _build_ccp_table():
    try:
        from haccp_dashboard.lib.dashboard_demo import get_batch_summary_frame
        df = get_batch_summary_frame()
        if df.empty:
            return html.Div("CCP 데이터 없음", style={"color": "#94a3b8", "padding": "20px", "textAlign": "center"})
        ccp_rows = df[~(df["hold_time_ok"].astype(bool) & df["hold_temp_ok"].astype(bool))].head(20)
        if ccp_rows.empty:
            return html.Div("CCP 이탈 없음 – 모든 배치 기준 충족",
                            style={"color": "#22c55e", "padding": "20px", "textAlign": "center", "fontWeight": "700"})
        header = html.Thead(html.Tr(
            [html.Th(h, style={"padding": "8px", "fontSize": "11px"}) for h in
             ["배치ID", "이름", "라인", "살균온도 OK", "보온시간 OK", "최고온도", "보온(분)", "위험도"]],
            style={"color": "#6b7280", "borderBottom": "1px solid #e5e7eb", "background": "#fef2f2"},
        ))

        def _ccp_row(r):
            temp_ok = bool(r.get("hold_temp_ok", True))
            time_ok = bool(r.get("hold_time_ok", True))
            return html.Tr([
                html.Td(str(r.get("batch_id", "")), style={"padding": "8px", "fontSize": "11px"}),
                html.Td(str(r.get("batch_name", "")), style={"fontSize": "11px"}),
                html.Td(f"L{r.get('line_id', '-')}", style={"fontSize": "11px"}),
                html.Td("OK" if temp_ok else "X", style={"fontSize": "13px"}),
                html.Td("OK" if time_ok else "X", style={"fontSize": "13px"}),
                html.Td(f"{r.get('peak_temp', 0.0):.1f}C", style={"fontSize": "11px"}),
                html.Td(f"{r.get('hold_minutes', 0.0):.0f}분", style={"fontSize": "11px"}),
                html.Td(html.Span(r.get("risk_level", "-"), style={
                    "background": "#fef2f2", "color": "#991b1b",
                    "padding": "2px 6px", "borderRadius": "4px", "fontSize": "10px", "fontWeight": "700",
                })),
            ], style={"borderBottom": "1px solid #f3f4f6"})

        rows_html = [_ccp_row(r) for _, r in ccp_rows.iterrows()]
        return html.Table([header, html.Tbody(rows_html)],
                          style={"width": "100%", "textAlign": "center", "fontSize": "11px"})
    except Exception:
        return html.Div("CCP 데이터 로드 실패", style={"color": "#94a3b8", "padding": "20px", "textAlign": "center"})


def layout(**_kwargs):
    from haccp_dashboard.lib.dashboard_demo import (
        get_default_heating_batch_id, get_heating_batch_options,
        get_report_rows, combined_temperature_figure,
    )
    batch_options = get_heating_batch_options(_DEFAULT_PERIOD)
    default_batch = get_default_heating_batch_id(_DEFAULT_PERIOD)
    report_rows = get_report_rows(_DEFAULT_PERIOD)
    try:
        temp_fig = combined_temperature_figure(default_batch)
    except Exception:
        import plotly.graph_objects as go
        temp_fig = go.Figure()
    analysis_payload = _build_analysis_payload(default_batch)

    return html.Div([
        html.H1("가열살균 공정 관리",
                style={"fontSize": "24px", "fontWeight": "900", "color": "#111827", "marginBottom": "18px"}),

        # 라인 탭 + 실시간 KPI
        html.Div([
            html.Div([html.Button(f"Line {i}", id={"type": "heating-line-btn", "index": i},
                                  n_clicks=0,
                                  style={"padding": "6px 16px", "borderRadius": "6px",
                                         "border": "1px solid #e5e7eb",
                                         "background": "#3b82f6" if i == 1 else "white",
                                         "color": "white" if i == 1 else "#374151",
                                         "fontWeight": "700", "fontSize": "12px", "cursor": "pointer",
                                         "marginRight": "6px"})
                      for i in range(1, 4)],
                     style={"marginBottom": "12px"}),
            html.Div(id="heating-realtime-kpi", children=_build_realtime_kpi_section(1)),
        ], style=_CARD_STYLE),

        # 컨트롤 바
        html.Div([
            html.Div([
                html.Label("기간", style={"fontSize": "12px", "fontWeight": "700", "color": "#64748b", "marginBottom": "4px"}),
                dcc.RadioItems(id="heating-period-select",
                               options=[{"label": "오늘", "value": "today"}, {"label": "주간", "value": "week"}],
                               value=_DEFAULT_PERIOD, inline=True,
                               inputStyle={"marginRight": "4px"},
                               labelStyle={"marginRight": "14px", "fontSize": "13px", "fontWeight": "600"}),
            ], style={"display": "flex", "flexDirection": "column"}),
            html.Div([
                html.Label("배치 선택", style={"fontSize": "12px", "fontWeight": "700", "color": "#64748b", "marginBottom": "4px"}),
                dcc.Dropdown(id="heating-batch-select", options=batch_options, value=default_batch,
                             clearable=False, style={"minWidth": "280px", "fontSize": "13px"}),
            ], style={"display": "flex", "flexDirection": "column"}),
        ], style={"display": "flex", "alignItems": "flex-end", "gap": "24px", **_CARD_STYLE}),

        # 3-컬럼 분석
        html.Div([
            html.Div([
                html.H3("공정 흐름", style={"marginBottom": "10px", "fontSize": "15px", "fontWeight": "800", "color": "#0f172a"}),
                html.Div(id="heating-process-flow", children=_build_process_flow_col(analysis_payload)),
            ], style={**_CARD_STYLE, "marginBottom": "0", "flex": "1", "minWidth": "200px"}),
            html.Div([
                html.H3("오염 유사도", style={"marginBottom": "10px", "fontSize": "15px", "fontWeight": "800", "color": "#0f172a"}),
                html.Div(id="heating-similarity-panel", children=_build_similarity_col(analysis_payload)),
            ], style={**_CARD_STYLE, "marginBottom": "0", "flex": "1.5", "minWidth": "240px"}),
            html.Div([
                html.H3("AI 판정", style={"marginBottom": "10px", "fontSize": "15px", "fontWeight": "800", "color": "#0f172a"}),
                html.Div(id="heating-ai-summary", children=_build_ai_summary_col(analysis_payload)),
            ], style={**_CARD_STYLE, "marginBottom": "0", "flex": "1", "minWidth": "200px"}),
        ], style={"display": "flex", "gap": "14px", "flexWrap": "wrap", "marginBottom": "16px"}),

        # 온도 프로파일 차트
        html.Div([
            html.H2("온도 프로파일", style={"marginBottom": "10px", "fontSize": "16px", "fontWeight": "800", "color": "#111827"}),
            dcc.Graph(id="heating-temp-chart", figure=temp_fig, config={"displayModeBar": False}),
        ], style=_CARD_STYLE),

        # 배치 이력 테이블
        html.Div([
            html.H2("배치 이력 보고서", style={"marginBottom": "14px", "fontSize": "16px", "fontWeight": "800", "color": "#111827"}),
            html.Div(id="heating-batch-table", children=_build_report_table(report_rows)),
        ], style={**_CARD_STYLE, "overflowX": "auto"}),

        # CCP 이탈 기록
        html.Div([
            html.H2("CCP 이탈 기록", style={"marginBottom": "14px", "fontSize": "16px", "fontWeight": "800", "color": "#111827"}),
            html.Div(id="heating-ccp-table", children=_build_ccp_table()),
        ], style={**_CARD_STYLE, "overflowX": "auto"}),

    ], style={"minWidth": "0", "padding": "4px 0"})


@callback(
    Output("heating-batch-select", "options"),
    Output("heating-batch-select", "value"),
    Output("heating-batch-table", "children"),
    Input("heating-period-select", "value"),
)
def _update_period(period: str):
    from haccp_dashboard.lib.dashboard_demo import (
        get_default_heating_batch_id, get_heating_batch_options, get_report_rows,
    )
    options = get_heating_batch_options(period)
    default_batch = get_default_heating_batch_id(period)
    rows = get_report_rows(period)
    return options, default_batch, _build_report_table(rows)


@callback(
    Output("heating-temp-chart", "figure"),
    Output("heating-process-flow", "children"),
    Output("heating-similarity-panel", "children"),
    Output("heating-ai-summary", "children"),
    Input("heating-batch-select", "value"),
    Input({"type": "heating-batch-btn", "index": dash.ALL}, "n_clicks"),
    State("heating-batch-select", "value"),
    prevent_initial_call=True,
)
def _update_charts(selected_from_dropdown, _btn_clicks, current_value):
    from dash import ctx
    import plotly.graph_objects as go
    from haccp_dashboard.lib.dashboard_demo import combined_temperature_figure

    triggered = ctx.triggered_id
    if isinstance(triggered, dict) and triggered.get("type") == "heating-batch-btn":
        batch_id = int(triggered["index"])
    else:
        batch_id = int(selected_from_dropdown or current_value or 0)

    if batch_id == 0:
        empty = go.Figure()
        msg = html.Div("배치를 선택하세요.", style={"color": "#94a3b8", "padding": "20px"})
        return empty, msg, msg, msg

    try:
        temp_fig = combined_temperature_figure(batch_id)
    except Exception:
        temp_fig = go.Figure()

    payload = _build_analysis_payload(batch_id)
    return temp_fig, _build_process_flow_col(payload), _build_similarity_col(payload), _build_ai_summary_col(payload)


@callback(
    Output("heating-realtime-kpi", "children"),
    Input({"type": "heating-line-btn", "index": dash.ALL}, "n_clicks"),
    prevent_initial_call=True,
)
def _update_line_kpi(_btn_clicks):
    from dash import ctx
    triggered = ctx.triggered_id
    if isinstance(triggered, dict) and triggered.get("type") == "heating-line-btn":
        line_id = int(triggered["index"])
    else:
        line_id = 1
    return _build_realtime_kpi_section(line_id)
'''

out_path = r'c:\haccp_dashboard\haccp_dashboard\pages\heating.py'
with open(out_path, 'w', encoding='utf-8') as f:
    f.write(new_content)
print(f'Written {len(new_content.splitlines())} lines to {out_path}')
