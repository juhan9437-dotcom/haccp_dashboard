"""가열살균 공정 관리 페이지 (/heating)

목적: QA/QC 담당자가 배치별 살균공정의 위험도를 판단하고 CCP 이탈 여부를 즉시 확인
"""
from __future__ import annotations
import dash
from dash import Input, Output, State, callback, dcc, html, no_update

from haccp_dashboard.utils.status_logic import STATUS_COLOR as _STATUS_COLORS, STATUS_BG as _STATUS_BG, STATUS_TEXT as _STATUS_TEXT
from haccp_dashboard.components.status_badges import CARD_STYLE as _CARD_STYLE

dash.register_page(__name__, path="/heating")

_DEFAULT_PERIOD = "week"


def _small_kpi(label, value, sub="", accent="#1565c0"):
    return html.Div([
        html.Div(label, className="ds-kpi-label"),
        html.Div(value, className="ds-kpi-value", style={"color": accent}),
        html.Div(sub, className="ds-kpi-sub") if sub else None,
    ], className="ds-kpi-card ds-kpi-card--sm", style={"borderLeftColor": accent})


def _build_realtime_kpi_section(line_id: int = 1):
    """가열살균 공정 4-KPI 카드."""
    try:
        from haccp_dashboard.lib.main_helpers import (
            get_today_data,
            load_process_batch_dataframe,
            resolve_process_csv_path,
        )
        frame = load_process_batch_dataframe(resolve_process_csv_path())
        today = get_today_data(frame)
    except Exception:
        today = None

    # 1) 현재 가동 중 배치 수 – 전체 라인(또는 선택 라인)의 진행 중 배치
    try:
        from haccp_dashboard.utils.state_manager import get_per_line_states
        states = get_per_line_states()
        active_batches = sum(
            1 for s in states.values()
            if s.get("state") not in (None, "Release", "Inspect", "")
        )
        if active_batches == 0:
            active_batches = len(states)  # 폴백: 운영 라인 수
    except Exception:
        active_batches = 0

    # 2) 금일 검사 건수 – 오늘 점검 완료된 배치 수
    try:
        if today is not None and not today.empty and "batch_id" in today.columns:
            inspection_count = int(today["batch_id"].nunique())
        else:
            inspection_count = 0
    except Exception:
        inspection_count = 0

    # 3) 핵심 CCP 이탈 배치 수 – 살균온도/유지시간 이탈만 카운트
    try:
        if today is not None and not today.empty:
            t_mask = today["ccp_hold_time_ok"].eq(0) if "ccp_hold_time_ok" in today.columns else today.index.to_series().eq(False)
            p_mask = today["ccp_hold_temp_ok"].eq(0) if "ccp_hold_temp_ok" in today.columns else today.index.to_series().eq(False)
            dev_mask = t_mask | p_mask
            if "batch_id" in today.columns:
                ccp_dev_count = int(today.loc[dev_mask, "batch_id"].nunique())
            else:
                ccp_dev_count = int(dev_mask.sum())
        else:
            ccp_dev_count = 0
    except Exception:
        ccp_dev_count = 0

    # 4) 물성 이상 배치 수 (pH/Kappa/점도 z≥1.0)
    try:
        from haccp_dashboard.lib.dashboard_demo import get_batch_summary_frame, _filter_summary
        today_summary = _filter_summary("today")
        if today_summary.empty:
            today_summary = get_batch_summary_frame().head(6)
        if not today_summary.empty:
            prop_z = today_summary[["max_abs_ph_z", "max_abs_mu_z", "max_abs_tau_z"]].max(axis=1)
            prop_warn_count = int((prop_z >= 2.0).sum())  # 경고 이상
            prop_caution_count = int(((prop_z >= 1.0) & (prop_z < 2.0)).sum())  # 주의
            stability_avg = float(today_summary["stability_score"].mean())
        else:
            prop_warn_count = prop_caution_count = 0
            stability_avg = 100.0
    except Exception:
        prop_warn_count = prop_caution_count = 0
        stability_avg = 100.0

    stab_color = "#ef4444" if stability_avg < 60 else "#f59e0b" if stability_avg < 80 else "#22c55e"
    ccp_color = "#ef4444" if ccp_dev_count > 0 else "#22c55e"

    kpis = [
        _small_kpi("현재 가동 중 배치 수", f"{active_batches}개",
                   "현재 생산·처리 중인 배치 수", "#3b82f6"),
        _small_kpi("금일 검사 건수", f"{inspection_count:,}건",
                   "오늘 점검 완료된 배치 수", "#6366f1"),
        _small_kpi("CCP 이탈 공정 수", f"{ccp_dev_count}공정",
                   "살균온도·유지시간 기준 이탈 공정", ccp_color),
        _small_kpi("공정안정도 지수", f"{stability_avg:.1f}%",
                   "전체 공정의 흔들림 없는 안정 운영 수준", stab_color),
    ]

    return html.Div([
        html.Div([
            html.H2("가열살균 공정 KPI", className="ds-section-header"),
            html.Div("금일 공정 현황 집계", className="ds-section-sub"),
        ], style={"marginBottom": "12px"}),
        html.Div(kpis, className="ds-kpi-grid"),
    ], style=_CARD_STYLE)


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
            text=f"<b>{name}</b><br><span style=\'font-size:10px\'>{val:.2f}</span>",
            showarrow=False, font=dict(size=10, color="#334155"), align="center",
        )
    fig.update_layout(
        height=280, margin=dict(l=40, r=40, t=20, b=20),
        xaxis=dict(visible=False, range=[-1.5, 1.5]),
        yaxis=dict(visible=False, range=[-1.5, 1.5], scaleanchor="x"),
        plot_bgcolor="white", paper_bgcolor="white", showlegend=False,
    )
    return fig


def _build_analysis_payload(batch_id) -> dict:
    """선택된 Batch의 공정값 → 오염 유사도 + 상태 판정 통합 payload.

    반환 키:
        stage, similarity_scores, top_name, top_score,
        judgement, message, action, model_pred, ccp_risk,
        sensor_reasons, factor_summary,
        batch_name, peak_temp, final_temp, final_ph, hold_minutes,
        stability_score, hold_time_ok, hold_temp_ok
    """
    try:
        from haccp_dashboard.lib.dashboard_demo import get_batch_summary_frame
        from haccp_dashboard.lib.main_helpers import (
            resolve_similarity_contamination_view,
            _infer_stage_from_state,
        )
        if not batch_id:
            return {}
        summary_frame = get_batch_summary_frame()
        if summary_frame.empty or int(batch_id) not in summary_frame["batch_id"].values:
            return {}
        row = summary_frame[summary_frame["batch_id"] == int(batch_id)].iloc[0]

        # stage는 last_state 컬럼 기준으로 동기화 (하드코딩 금지)
        last_state = row.get("last_state") or row.get("current_stage") or "Hold"
        stage = _infer_stage_from_state(last_state)

        # 통합 유사도 뷰 (contamination 컬럼 참조 없음)
        view = resolve_similarity_contamination_view(row, stage=stage)

        ph = float(row.get("final_ph", 6.7))
        peak_t = float(row.get("peak_temp", 64.0))
        final_t = float(row.get("final_temp", 7.0))
        hold_m = float(row.get("hold_minutes", 15.0))
        stability = float(row.get("stability_score", 100.0))
        hold_time_ok = bool(row.get("hold_time_ok", True))
        hold_temp_ok = bool(row.get("hold_temp_ok", True))
        mu_z = float(row.get("max_abs_mu_z", 0.0) or 0.0)
        tau_z = float(row.get("max_abs_tau_z", 0.0) or 0.0)
        ph_z = float(row.get("max_abs_ph_z", 0.0) or 0.0)

        # 센서 이상 항목
        sensor_reasons = []
        if abs(ph - 6.7) > 0.1:
            sensor_reasons.append(f"pH {ph:.2f} – 기준(6.6~6.8) 이탈")
        if not hold_temp_ok:
            sensor_reasons.append(f"살균 온도 {peak_t:.1f}°C – CCP 한계 위반")
        # hold_time_ok=False 는 Hold 구간이 완료된 후에만 의미 있음.
        # HeatUp 단계에서 hold_minutes=0은 정상 상태이므로 경고 제외.
        if not hold_time_ok and stage in ("Hold", "Cool", "Discharge"):
            sensor_reasons.append(f"살균 유지시간 {hold_m:.0f}분 – CCP 기준(15분) 미달")
        if stage == "Cool" and final_t > 7.0:
            sensor_reasons.append(f"냉각 최종온도 {final_t:.1f}°C – 7°C 초과")
        if ph_z >= 2.0:
            sensor_reasons.append(f"pH 편차 큰 폭으로 이탈 – 정상 우유 패턴 대비 명확한 이상")
        elif ph_z >= 1.0:
            sensor_reasons.append(f"pH 이상징후 – CCP 연계 물성 모니터링 필요")
        if mu_z >= 2.0:
            sensor_reasons.append(f"점도 큰 폭으로 이탈 – 우유 응고·조성 변화 가능성")
        elif mu_z >= 1.0:
            sensor_reasons.append(f"점도 이상징후 – 우유 물성 확인 필요")
        if tau_z >= 2.0:
            sensor_reasons.append(f"Kappa 큰 폭으로 이탈 – 세정제 잔류 가능성")
        elif tau_z >= 1.0:
            sensor_reasons.append(f"Kappa 이상징후 – 이온 농도 변동 감지")

        # factor 요약 (최고 오염원을 높게 만든 주요 factor 설명)
        top_name = view["top_name"]
        factor_summary = _build_factor_summary(top_name, stage, view["model_pred"], hold_time_ok, hold_temp_ok, ph, peak_t, final_t, hold_m, stability)

        return {
            "similarity_scores": view["similarity_scores"],
            "top_name": top_name,
            "top_score": view["top_score"],
            "stage": stage,
            "last_state": last_state,  # CSV 원본 state (heating 6단계 위치 표시에 사용)
            "judgement": view["status"],
            "message": view["message"],
            "action": view["action"],
            "model_pred": view["model_pred"],
            "ccp_risk": view["ccp_risk"],
            "sensor_reasons": sensor_reasons,
            "factor_summary": factor_summary,
            "batch_name": str(row.get("batch_name", "")),
            "peak_temp": peak_t,
            "final_temp": final_t,
            "final_ph": ph,
            "hold_minutes": hold_m,
            "stability_score": stability,
            "hold_time_ok": hold_time_ok,
            "hold_temp_ok": hold_temp_ok,
            "mu_z": mu_z,
            "tau_z": tau_z,
            "ph_z": ph_z,
        }
    except Exception:
        return {}


def _build_factor_summary(top_name, stage, model_pred, hold_time_ok, hold_temp_ok, ph, peak_t, final_t, hold_m, stability):
    """최고 유사 오염원이 높게 나온 주요 factor를 한국어로 설명."""
    lines = []
    stage_label = {"HeatUp": "가열", "Hold": "살균 유지", "Cool": "냉각"}.get(stage, stage)
    lines.append(f"현재 공정 단계: {stage_label}")

    if top_name in ("NaOH", "HNO3"):
        if ph > 6.8:
            lines.append(f"pH {ph:.2f} – 알칼리 잔류 가능성 (NaOH 세정제 패턴)")
        elif ph < 6.6:
            lines.append(f"pH {ph:.2f} – 산성 오염 가능성 (HNO3 세정제 패턴)")
        if stage == "HeatUp":
            lines.append("가열 단계: 세정제 잔류 위험 집중 구간")
    elif top_name == "E.coli":
        if not (hold_time_ok and hold_temp_ok):
            lines.append("CCP 이탈: E.coli 사멸 조건 미충족")
        # hold_m은 Hold 구간 경과 시간이므로, 아직 Hold에 진입하지 않은 단계(HeatUp 등)에서는 0이 정상
        if stage in ("Hold", "Cool") and hold_m < 15:
            lines.append(f"살균 유지 시간 {hold_m:.0f}분 – CCP 기준(15분) 미달")
        elif stage == "HeatUp":
            lines.append("가열 진행 중 – 살균 유지 구간 진입 대기 중")
    elif top_name == "Salmonella":
        if not (hold_time_ok and hold_temp_ok):
            lines.append("CCP 이탈: 살균 유지 구간 온도·시간 기준 이탈")
        if stage == "HeatUp":
            lines.append(f"가열 진행 중 ((도달 예정 {peak_t:.1f}°C) – 살균 유지 조건 확인 시작 전")
        elif abs(peak_t - 72.0) > 4.0:
            lines.append(f"살균 온도 {peak_t:.1f}°C – Salmonella 사멸 기준 이탈")
    elif top_name == "Listeria":
        # Listeria 냉각 내성은 냉각 단계에서만 의미 있음
        if stage == "Cool":
            if final_t > 7.0:
                lines.append(f"냉각 후 온도 {final_t:.1f}°C – Listeria 냉각 내성 잔존 위험")
            lines.append("냉각 단계: 냉각 내성 미생물 잔존 위험 구간")
        else:
            lines.append(f"현재 {stage_label} 단계 – 냉각 후 온도 모니터링 필요")

    if model_pred == "bio":
        lines.append("딥러닝 모델: 생물학적 오염 패턴 감지")
    elif model_pred == "chem":
        lines.append("딥러닝 모델: 화학적 혼입 패턴 감지")

    if stability < 80:
        lines.append(f"공정 안정도 {stability:.1f}% – 기준(80%) 미달")

    return lines


def _build_process_flow_col(payload: dict):
    from haccp_dashboard.lib.process_spec import (
        HEATING_STAGE_ORDER, HEATING_STAGE_LABELS, HEATING_CSV_MAP,
    )
    if not payload:
        return html.Div("데이터 없음", style={"color": "#94a3b8", "padding": "20px"})

    batch_name = payload.get("batch_name", "-")
    peak_t = payload.get("peak_temp", 0.0)
    final_ph = payload.get("final_ph", 0.0)
    hold_m = payload.get("hold_minutes", 0.0)
    final_t = payload.get("final_temp", 0.0)
    hold_time_ok = payload.get("hold_time_ok", True)
    hold_temp_ok = payload.get("hold_temp_ok", True)

    # last_state(CSV 원본) → 6단계 heating stage 위치
    last_state = payload.get("last_state", "Hold")
    current_h_stage = HEATING_CSV_MAP.get(str(last_state), "Hold")

    stage_order = HEATING_STAGE_ORDER  # ["Idle","PastFill","HeatUp","Hold","Cool","Discharge"]
    stage_labels = HEATING_STAGE_LABELS
    mu_z = payload.get("mu_z", 0.0)
    tau_z = payload.get("tau_z", 0.0)
    ph_z = payload.get("ph_z", 0.0)

    def _prop_chip(label, z):
        """현재 단계 내부에 표시할 목성 논트 칩 (현장 한국어 표현)."""
        if z >= 2.0:
            status, c_bg, c_fg, c_bd = "이탈 큰 폭", "#fef2f2", "#991b1b", "#fecaca"
        elif z >= 1.0:
            status, c_bg, c_fg, c_bd = "경미 이탈", "#fffbeb", "#b45309", "#fde68a"
        else:
            status, c_bg, c_fg, c_bd = "정상", "#f0fdf4", "#166534", "#bbf7d0"
        return html.Div([
            html.Div(label, style={"fontSize": "10px", "color": "#64748b",
                                   "fontWeight": "700", "marginBottom": "3px"}),
            html.Div(status, style={
                "fontSize": "13px", "fontWeight": "800", "color": c_fg,
            }),
        ], style={
            "flex": "1", "minWidth": "60px",
            "background": c_bg,
            "border": f"1px solid {c_bd}",
            "borderRadius": "8px",
            "padding": "8px 10px",
            "textAlign": "center",
        })

    stage_descs = {
        "Idle":      "원유 수유·청정·저유·균질화 진행",
        "PastFill":  "원유 살균기 투입 · 균질화 완료 → 가열 준비",
        "HeatUp":    f"목표 72°C 도달 · 현재 최고 {peak_t:.1f}°C",
        "Hold":      f"살균 유지 {hold_m:.0f}분 · {'CCP 충족' if hold_time_ok and hold_temp_ok else 'CCP 이탈'}",
        "Cool":      f"최종온도 {final_t:.1f}°C · pH {final_ph:.2f}",
        "Discharge": "출하 전 품질 검증 단계",
    }
    stage_nodes = []
    curr_idx = stage_order.index(current_h_stage) if current_h_stage in stage_order else 3
    for idx, st in enumerate(stage_order):
        is_current = (idx == curr_idx)
        is_done = idx < curr_idx
        if is_current:
            row_state = "active"
        elif is_done:
            row_state = "done"
        else:
            row_state = "pending"

        current_badge = (
            html.Span("현재 단계", style={
                "fontSize": "10px", "fontWeight": "700",
                "background": "#dbeafe", "color": "#1d4ed8",
                "borderRadius": "999px", "padding": "3px 10px",
                "alignSelf": "flex-end",
                "marginTop": "8px",
            }) if is_current else None
        )

        prop_row = None
        if is_current and st in ("HeatUp", "Hold", "Cool"):
            prop_row = html.Div([
                _prop_chip("pH", abs(ph_z)),
                _prop_chip("점도", abs(mu_z)),
                _prop_chip("Kappa", abs(tau_z)),
            ], style={"display": "flex", "gap": "8px", "marginTop": "10px"})

        name_color = "#0f172a" if (is_current or is_done) else "#94a3b8"
        desc_color = "#64748b" if (is_current or is_done) else "#cbd5e1"

        card_inner = html.Div([
            html.Span(stage_labels[st],
                      style={"color": name_color, "fontSize": "13.5px",
                             "fontWeight": "700", "lineHeight": "1.3"}),
            html.Div(stage_descs[st],
                     style={"fontSize": "11.5px", "marginTop": "3px",
                            "color": desc_color, "lineHeight": "1.4"}),
        ])

        card_children = [card_inner]
        if prop_row is not None:
            card_children.append(prop_row)
        if current_badge is not None:
            card_children.append(current_badge)

        stage_nodes.append(html.Div([
            html.Div(html.Div(className="ds-pipeline-dot"),
                     className="ds-pipeline-rail"),
            html.Div(card_children,
                     className="ds-pipeline-card",
                     style={"display": "flex", "flexDirection": "column"}),
        ], className=f"ds-pipeline-row ds-pipeline-row--{row_state}"))
    return html.Div([
        html.Div(stage_nodes, className="ds-pipeline"),
        html.Div(f"현재 단계: {stage_labels.get(current_h_stage, current_h_stage)}",
                  className="ds-flow-current-bar"),
    ])


def _build_similarity_col(payload: dict):
    if not payload:
        return html.Div("배치를 선택하면 오염 유사도 분석 결과가 표시됩니다.",
                        style={"color": "#94a3b8", "padding": "20px", "fontSize": "13px"})
    scores = payload.get("similarity_scores", {})
    stage = payload.get("stage", "Hold")
    top_name = payload.get("top_name", "-")
    top_score = payload.get("top_score", 0.0)
    judgement = payload.get("judgement", "정상")
    batch_name = payload.get("batch_name", "-")
    factor_summary = payload.get("factor_summary", [])
    model_pred = payload.get("model_pred", "no")

    stage_label = {"HeatUp": "가열", "Hold": "살균 유지", "Cool": "냉각"}.get(stage, stage)
    stage_desc = {
        "HeatUp": "가열 단계 기준 – 세정제·화학물질 잔류 위험 집중 분석",
        "Hold":   "살균 유지 기준 – 미생물 사멸 조건 집중 분석",
        "Cool":   "냉각 단계 기준 – 냉각 내성 미생물 잔존 집중 분석",
    }.get(stage, "")

    level_palette = {
        "정상": ("#ecfdf5", "#166534", "#22c55e"),
        "경고": ("#fffbeb", "#b45309", "#f59e0b"),
        "위험": ("#fef2f2", "#991b1b", "#ef4444"),
    }
    bg, fg, border_c = level_palette.get(judgement, ("#f8fafc", "#374151", "#94a3b8"))

    # 레이더 차트 (카드 상단 top_name과 반드시 동일한 scores 사용)
    fig = _similarity_polygon_figure(scores, stage)

    # model_pred 라벨
    pred_label_map = {"no": ("정상", "#ecfdf5", "#166534"), "chem": ("화학 패턴", "#fffbeb", "#b45309"), "bio": ("생물학 패턴", "#fef2f2", "#991b1b")}
    pred_text, pred_bg, pred_fg = pred_label_map.get(model_pred, ("알 수 없음", "#f1f5f9", "#64748b"))

    return html.Div([
        # ── 상단 요약 카드 ──────────────────────────────────
        html.Div([
            html.Div([
                html.Div("최고 유사 오염원", style={"fontSize": "11px", "color": "#64748b", "fontWeight": "700", "marginBottom": "2px"}),
            ]),
            html.Div([
                html.Span(top_name, style={"fontSize": "22px", "fontWeight": "900", "color": fg, "marginRight": "8px"}),
                html.Span(f"{top_score:.2f}", style={"fontSize": "16px", "fontWeight": "700", "color": fg}),
            ]),
        ], style={
            "background": bg,
            "border": f"1px solid {border_c}40",
            "borderLeft": f"4px solid {border_c}",
            "borderRadius": "10px",
            "padding": "12px 14px",
            "marginBottom": "10px",
            "display": "flex",
            "justifyContent": "space-between",
            "alignItems": "center",
        }),

        # ── 공정 단계 + 모델 예측 ──────────────────────────
        html.Div([
            html.Div([
                html.Span("공정 단계: ", style={"fontSize": "11px", "color": "#94a3b8", "fontWeight": "600"}),
                html.Span(stage_label, style={"fontSize": "11px", "color": "#0f172a", "fontWeight": "800"}),
            ]),
            html.Span(pred_text, style={
                "fontSize": "10px", "fontWeight": "700", "padding": "2px 8px",
                "borderRadius": "999px", "background": pred_bg, "color": pred_fg,
            }),
        ], style={"display": "flex", "justifyContent": "space-between", "alignItems": "center", "marginBottom": "6px"}),
        html.Div(stage_desc, style={"fontSize": "10px", "color": "#6b7280", "marginBottom": "10px"}),

        # ── 레이더 차트 (scores와 top_name 완전 동기화) ───────
        dcc.Graph(figure=fig, config={"displayModeBar": False}, style={"marginBottom": "10px"}),

        # ── 5개 오염원 점수 바 (CSS, 내림차순) ─────────────
        *[html.Div([
            html.Div(name, style={"fontSize": "11px", "fontWeight": "700",
                                  "color": fg if name == top_name else "#374151",
                                  "minWidth": "80px"}),
            html.Div([
                html.Div(style={
                    "width": f"{min(score * 100, 100):.1f}%",
                    "height": "8px",
                    "background": border_c if name == top_name else "#94a3b8",
                    "borderRadius": "4px",
                }),
            ], style={"flex": "1", "height": "8px", "background": "#e5e7eb",
                      "borderRadius": "4px", "overflow": "hidden", "margin": "0 8px"}),
            html.Div(f"{score:.2f}", style={"fontSize": "11px", "fontWeight": "700",
                                            "color": fg if name == top_name else "#6b7280",
                                            "minWidth": "32px", "textAlign": "right"}),
        ], style={"display": "flex", "alignItems": "center", "marginBottom": "5px"})
          for name, score in sorted(scores.items(), key=lambda kv: -kv[1])],

        # ── 주요 factor 설명 ───────────────────────────────
        html.Div([
            html.Div("유사도 상승 주요 원인", style={"fontSize": "11px", "color": "#64748b", "fontWeight": "700", "marginBottom": "6px"}),
            *([html.Div(f"• {line}", style={"fontSize": "11px", "color": "#374151", "marginBottom": "3px", "lineHeight": "1.4"})
               for line in factor_summary] if factor_summary else [
                html.Div("주요 이상 factor 없음", style={"fontSize": "11px", "color": "#22c55e", "fontWeight": "600"})
            ]),
        ], style={"background": "#f8fafc", "borderRadius": "8px", "padding": "10px 12px", "marginTop": "8px"}),
    ])


def _build_ai_summary_col(payload: dict):
    if not payload:
        return html.Div("배치를 선택하면 AI 판정 요약이 표시됩니다.",
                        style={"color": "#94a3b8", "padding": "20px", "fontSize": "13px"})
    level = payload.get("judgement", "정상")
    message = payload.get("message", "")
    action = payload.get("action", "")
    reasons = payload.get("sensor_reasons", [])
    factor_summary = payload.get("factor_summary", [])
    top_name = payload.get("top_name", "-")
    top_score = payload.get("top_score", 0.0)
    stage = payload.get("stage", "Hold")
    batch_name = payload.get("batch_name", "-")
    model_pred = payload.get("model_pred", "no")
    stability = payload.get("stability_score", 100.0)
    ccp_risk = payload.get("ccp_risk", 0.0)
    hold_time_ok = payload.get("hold_time_ok", True)
    hold_temp_ok = payload.get("hold_temp_ok", True)
    ph = payload.get("final_ph", 6.7)
    mu_z = payload.get("mu_z", 0.0)
    tau_z = payload.get("tau_z", 0.0)
    ph_z = payload.get("ph_z", 0.0)

    stage_label = {"HeatUp": "가열", "Hold": "살균 유지", "Cool": "냉각"}.get(stage, stage)

    # 3단계 팔레트
    level_palette = {
        "정상": ("#ecfdf5", "#166534", "#22c55e"),
        "경고": ("#fffbeb", "#b45309", "#f59e0b"),
        "위험": ("#fef2f2", "#991b1b", "#ef4444"),
    }
    bg, fg, border_c = level_palette.get(level, ("#f8fafc", "#374151", "#94a3b8"))

    # 판정 기준 설명 (3단계)
    criteria_rows = [
        ("위험", "#fef2f2", "#991b1b", "핵심 CCP – 살균 온도 또는 유지시간 기준 이탈"),
        ("경고", "#fffbeb", "#b45309", "물성 이상 – pH·Kappa·점도·밀도 중 하나 이상 정상 범위 이탈"),
        ("정상", "#ecfdf5", "#166534", "온도·유지시간·pH·Kappa·점도·밀도 모두 정상 범위 내"),
    ]
    criteria_items = []
    for label, cb, ct, desc in criteria_rows:
        is_current = (label == level)
        criteria_items.append(html.Div([
            html.Span(label, style={
                "fontSize": "11px", "fontWeight": "800",
                "background": cb, "color": ct,
                "borderRadius": "999px", "padding": "3px 12px",
                "minWidth": "44px", "textAlign": "center",
                "border": f"1.5px solid {ct}" if is_current else f"1px solid {ct}40",
                "flexShrink": "0",
            }),
            html.Span(desc, style={
                "fontSize": "11px", "color": ct if is_current else "#64748b",
                "fontWeight": "700" if is_current else "500",
                "marginLeft": "10px", "lineHeight": "1.45",
            }),
        ], style={
            "display": "flex", "alignItems": "flex-start",
            "padding": "7px 10px",
            "borderRadius": "8px",
            "background": cb if is_current else "transparent",
            "marginBottom": "4px",
        }))

    # ── 핵심 3줄 요약 ────────────────────────────────────
    summary_lines = []
    if not (hold_time_ok and hold_temp_ok):
        summary_lines.append("핵심 CCP(온도·유지시간) 기준 이탈")
    else:
        summary_lines.append("핵심 CCP(온도·유지시간) 기준 충족")

    prop_issues = []
    if abs(ph_z) >= 1.0:
        prop_issues.append("pH")
    if abs(mu_z) >= 1.0:
        prop_issues.append("점도")
    if abs(tau_z) >= 1.0:
        prop_issues.append("Kappa")
    if prop_issues:
        summary_lines.append("물성 경미한 이상징후 – " + "·".join(prop_issues) + " 정상 범위 이탈")
    else:
        summary_lines.append("pH·점도·Kappa 정상 패턴 내")
    summary_lines.append(f"{top_name} 유사도 {top_score:.2f}로 가장 높음")

    # ── 이상 감지 항목 가로 pill ─────────────────────────
    detection_chips = [("pH", abs(ph_z)), ("점도", abs(mu_z)), ("Kappa", abs(tau_z))]
    chip_nodes = []
    for name, z in detection_chips:
        if z >= 2.0:
            status, c_bg, c_fg, c_bd = "이탈 큰 폭", "#fef2f2", "#991b1b", "#fecaca"
        elif z >= 1.0:
            status, c_bg, c_fg, c_bd = "경미 이탈", "#fffbeb", "#b45309", "#fde68a"
        else:
            status, c_bg, c_fg, c_bd = "정상", "#f0fdf4", "#166534", "#bbf7d0"
        chip_nodes.append(html.Span(
            f"{name} · {status}",
            style={
                "fontSize": "12.5px", "fontWeight": "800",
                "background": c_bg, "color": c_fg,
                "border": f"1px solid {c_bd}",
                "borderRadius": "999px", "padding": "8px 18px",
            },
        ))

    # ── 판정 기준 토글 (html.Details) ────────────────────
    criteria_block = html.Details([
        html.Summary("판정 기준 보기", style={
            "cursor": "pointer", "fontSize": "11px", "fontWeight": "700",
            "color": "#1d4ed8", "padding": "5px 12px",
            "background": "#eff6ff", "borderRadius": "999px",
            "border": "1px solid #bfdbfe", "display": "inline-block",
            "listStyle": "none",
        }),
        html.Div(criteria_items, style={
            "background": "#f8fafc", "borderRadius": "10px",
            "padding": "10px", "marginTop": "8px",
            "border": "1px solid #e2e8f0",
        }),
    ])

    label_style = {"fontSize": "12px", "color": "#0f172a",
                   "fontWeight": "800", "marginBottom": "8px"}

    return html.Div([
        # ── 히어로 카드 (중앙 정렬 판정) ─────────────────
        html.Div([
            html.Div("AI 판정 요약", style={
                "fontSize": "11px", "color": "#64748b",
                "fontWeight": "700", "letterSpacing": "0.04em",
                "marginBottom": "8px",
            }),
            html.Div(level, style={
                "fontSize": "36px", "fontWeight": "900",
                "color": fg, "lineHeight": "1.05",
            }),
            html.Div(f"BATCH-{batch_name} · {stage_label}", style={
                "fontSize": "12.5px", "color": "#475569",
                "fontWeight": "600", "marginTop": "8px",
            }),
            html.Div([
                html.Span("최고 유사 오염원: ", style={"fontSize": "12px",
                                                  "color": "#64748b"}),
                html.Span(top_name, style={"fontSize": "13px", "fontWeight": "800",
                                           "color": fg}),
                html.Span(f" {top_score:.2f}", style={"fontSize": "13px",
                                                     "color": fg,
                                                     "marginLeft": "4px",
                                                     "fontWeight": "700"}),
            ], style={"marginTop": "6px"}),
        ], style={
            "background": bg,
            "border": f"1px solid {border_c}40",
            "borderRadius": "14px",
            "padding": "24px 18px",
            "marginBottom": "18px",
            "textAlign": "center",
        }),

        # ── 공정 분석 근거 (요약) + 판정 기준 토글 ────────
        html.Div([
            criteria_block,
            html.Div("공정 분석 근거 (요약)", style={**label_style, "marginTop": "10px"}),
            html.Div([
                html.Div([
                    html.Span("•", style={"color": border_c, "fontWeight": "900",
                                          "fontSize": "16px", "marginRight": "10px",
                                          "lineHeight": "1"}),
                    html.Span(line, style={"fontSize": "12.5px", "color": "#1f2937",
                                            "lineHeight": "1.55"}),
                ], style={"display": "flex", "alignItems": "flex-start",
                          "marginBottom": "8px"})
                for line in summary_lines
            ], style={
                "background": "#f8fafc", "borderRadius": "10px",
                "padding": "14px 16px", "border": "1px solid #e2e8f0",
            }),
        ], style={"marginBottom": "16px"}),

        # ── 이상 감지 항목 (가로 pill) ──────────────────
        html.Div([
            html.Div("이상 감지 항목", style=label_style),
            html.Div(chip_nodes, style={"display": "flex", "gap": "10px",
                                        "flexWrap": "wrap"}),
        ], style={"marginBottom": "16px"}),

        # ── 권고 조치 (단일 pill) ───────────────────────
        html.Div([
            html.Div("권고 조치", style=label_style),
            html.Div(action, style={
                "fontSize": "13px", "fontWeight": "700", "color": fg,
                "background": bg, "borderRadius": "10px",
                "padding": "12px 16px",
                "borderLeft": f"4px solid {border_c}",
                "lineHeight": "1.5",
            }),
        ], style={"marginBottom": "16px"}),

        # ── 공정 상태 요약 푸터 ──────────────────────────
        html.Div([
            html.Div("공정 상태 요약", style=label_style),
            html.Div([
                html.Div([
                    html.Div("공정 안정도", style={"fontSize": "11px",
                                                "color": "#94a3b8",
                                                "fontWeight": "600",
                                                "marginBottom": "4px"}),
                    html.Div(f"{stability:.1f}%", style={
                        "fontSize": "18px", "fontWeight": "800",
                        "color": "#ef4444" if stability < 60 else "#f59e0b" if stability < 80 else "#22c55e",
                    }),
                ], style={"flex": "1"}),
                html.Div(style={"width": "1px", "background": "#e2e8f0",
                                "alignSelf": "stretch"}),
                html.Div([
                    html.Div("핵심 CCP", style={"fontSize": "11px",
                                              "color": "#94a3b8",
                                              "fontWeight": "600",
                                              "marginBottom": "4px"}),
                    html.Div("이탈" if ccp_risk >= 1.0 else "충족", style={
                        "fontSize": "18px", "fontWeight": "800",
                        "color": "#ef4444" if ccp_risk >= 1.0 else "#22c55e",
                    }),
                ], style={"flex": "1", "paddingLeft": "18px"}),
            ], style={
                "display": "flex", "alignItems": "center", "gap": "18px",
                "background": "#f8fafc", "borderRadius": "10px",
                "padding": "14px 18px", "border": "1px solid #e2e8f0",
            }),
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
         ["라인", "배치", "일자", "오염 판정", "최고 온도", "편차", "보온 시간", "안정도", "상태", "상세"]],
        style={"color": "#6b7280", "borderBottom": "1px solid #e5e7eb", "background": "#f9fafb"},
    ))

    def _row(r):
        deviation = r.get("deviation", 0.0)
        dev_color = "#ef4444" if abs(deviation) > 1.5 else "#f59e0b" if abs(deviation) > 0.5 else "#22c55e"
        stability = r.get("stability_score", 0.0)
        stab_color = "#ef4444" if stability < 60 else "#f59e0b" if stability < 80 else "#22c55e"
        return html.Tr([
            html.Td(f"L{r.get('line_id', '-')}", style={"padding": "12px 8px", "fontSize": "12px"}),
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


def _get_line_dropdown_options() -> list[dict]:
    """main.py '라인별 즉시 조치 Batch 현황'과 동일한 소스(get_per_line_states)로
    'Line X  –  BATCH-XXX' 형식의 드롭다운 옵션을 반환한다."""
    try:
        from haccp_dashboard.utils.state_manager import get_per_line_states
        states = get_per_line_states()
        opts = []
        for lid in sorted(states.keys()):
            s = states[lid]
            bn = s.get("batch_name") or "-"
            opts.append({"label": f"Line {lid}  –  {bn}", "value": lid})
        return opts if opts else [{"label": f"Line {i}", "value": i} for i in range(1, 4)]
    except Exception:
        return [{"label": f"Line {i}", "value": i} for i in range(1, 4)]


def layout(**_kwargs):
    from haccp_dashboard.lib.dashboard_demo import (
        get_default_heating_batch_id, get_heating_batch_options,
        get_report_rows,
    )
    from haccp_dashboard.lib.csv_inference_panel import (
        build_csv_upload_status_panel, build_csv_inference_idle_panel,
    )
    _line_opts = _get_line_dropdown_options()
    _line_default = _line_opts[0]["value"] if _line_opts else 1

    # 기본 라인의 배치로 즉시 렌더링
    try:
        from haccp_dashboard.utils.state_manager import get_per_line_states
        _default_batch_id = get_per_line_states().get(int(_line_default), {}).get("batch_id")
    except Exception:
        _default_batch_id = None
    analysis_payload = _build_analysis_payload(_default_batch_id)

    return html.Div([
        html.H1("가열살균 공정 관리", className="ds-page-title"),

        # 실시간 KPI (전체 라인 집계)
        html.Div([
            html.Div(id="heating-realtime-kpi", children=_build_realtime_kpi_section()),
        ], style=_CARD_STYLE),

        # 3-컬럼 분석
        html.Div([
            html.Div([
                html.Div([
                    html.H3("공정 흐름", className="ds-section-header",
                             style={"margin": "0", "fontSize": "15px"}),
                    dcc.Dropdown(
                        id="heating-line-select",
                        options=_line_opts,
                        value=_line_default,
                        clearable=False,
                        style={"width": "190px", "fontSize": "12px"},
                    ),
                    dcc.Interval(
                        id="heating-line-opts-interval",
                        interval=30_000,
                        n_intervals=0,
                    ),
                ], style={"display": "flex", "alignItems": "center", "gap": "12px", "marginBottom": "10px"}),
                html.Div(id="heating-process-flow", children=_build_process_flow_col(analysis_payload)),
            ], style={**_CARD_STYLE, "marginBottom": "0", "flex": "1", "minWidth": "200px"}),
            html.Div([
                html.H3("오염 유사도", className="ds-section-header",
                         style={"marginBottom": "10px", "fontSize": "15px"}),
                html.Div(id="heating-similarity-panel", children=_build_similarity_col(analysis_payload)),
            ], style={**_CARD_STYLE, "marginBottom": "0", "flex": "1", "minWidth": "240px"}),
            html.Div([
                html.H3("가열살균공정 AI 요약", className="ds-section-header",
                         style={"marginBottom": "10px", "fontSize": "15px"}),
                html.Div(id="heating-ai-summary", children=_build_ai_summary_col(analysis_payload)),
            ], style={**_CARD_STYLE, "marginBottom": "0", "flex": "1.7", "minWidth": "320px"}),
        ], style={"display": "flex", "gap": "14px", "flexWrap": "wrap", "marginBottom": "16px"}),

        # CSV 오염 추론 패널
        dcc.Store(id="heating-csv-upload-store"),
        html.Div([
            html.H2("딥러닝 오염 유사도 분석", className="ds-section-header",
                     style={"marginBottom": "14px"}),
            html.Div([
                # 좌: 업로드 패널
                html.Div([
                    html.Div(id="heating-csv-upload-summary",
                             children=build_csv_upload_status_panel()),
                    dcc.Upload(
                        id="heating-csv-upload",
                        children=html.Div([
                            html.Div("CSV 업로드", className="inspection-upload-drop-title"),
                            html.Div("센서 시계열 CSV를 드래그하거나 클릭해 선택합니다.",
                                     className="inspection-upload-drop-copy"),
                        ]),
                        className="inspection-upload-dropzone",
                        accept=".csv",
                        multiple=False,
                        style={"marginTop": "12px"},
                    ),
                    html.Button(
                        "추론 실행",
                        id="heating-run-csv-inference",
                        n_clicks=0,
                        disabled=True,
                        className="inspection-run-button",
                        style={"marginTop": "12px", "width": "100%", "height": "48px",
                               "fontSize": "14px"},
                    ),
                ], style={"flex": "1", "minWidth": "300px", "maxWidth": "420px"}),
                # 우: AI 결과 패널
                html.Div(
                    id="heating-csv-inference-result",
                    children=build_csv_inference_idle_panel(),
                    style={"flex": "2", "minWidth": "320px"},
                ),
            ], style={"display": "flex", "gap": "16px", "flexWrap": "wrap"}),
        ], style=_CARD_STYLE),

        # CCP 이탈 기록
        html.Div([
            html.H2("CCP 이탈 기록", className="ds-section-header",
                     style={"marginBottom": "14px"}),
            html.Div(id="heating-ccp-table", children=_build_ccp_table()),
        ], style={**_CARD_STYLE, "overflowX": "auto"}),

        # 배치 이력 테이블
        html.Div([
            html.H2("배치 이력 보고서", className="ds-section-header",
                     style={"marginBottom": "14px"}),
            html.Div(
                html.Div(id="heating-batch-table", children=_build_report_table(get_report_rows("today"))),
                className="compact-scroll",
                style={"maxHeight": "320px", "overflowY": "auto", "border": "1px solid #edf1f5", "borderRadius": "14px", "background": "white"},
            ),
        ], style={**_CARD_STYLE, "overflowX": "auto"}),

    ], style={"minWidth": "0", "padding": "4px 0"})


@callback(
    Output("heating-line-select", "options"),
    Input("heating-line-opts-interval", "n_intervals"),
)
def _refresh_line_options(_):
    """30초마다 드롭다운 옵션을 main.py와 동일한 소스로 갱신한다."""
    return _get_line_dropdown_options()


@callback(
    Output("heating-process-flow", "children"),
    Output("heating-similarity-panel", "children"),
    Output("heating-ai-summary", "children"),
    Input({"type": "heating-batch-btn", "index": dash.ALL}, "n_clicks"),
    Input("heating-selected-batch-store", "data"),
    Input("heating-line-select", "value"),
    prevent_initial_call=True,
)
def _update_charts(_btn_clicks, store_data, line_value):
    from dash import ctx

    triggered = ctx.triggered_id
    batch_id = None

    if isinstance(triggered, dict) and triggered.get("type") == "heating-batch-btn":
        batch_id = int(triggered["index"])
    elif triggered == "heating-selected-batch-store" and store_data:
        batch_id = store_data.get("batch_id")
    elif triggered == "heating-line-select" and line_value is not None:
        try:
            from haccp_dashboard.utils.state_manager import get_per_line_states
            states = get_per_line_states()
            batch_id = states.get(int(line_value), {}).get("batch_id")
        except Exception:
            batch_id = None

    if not batch_id:
        return dash.no_update, dash.no_update, dash.no_update

    payload = _build_analysis_payload(batch_id)
    return _build_process_flow_col(payload), _build_similarity_col(payload), _build_ai_summary_col(payload)


@callback(
    Output("heating-csv-upload-store", "data"),
    Output("heating-csv-upload", "children"),
    Output("heating-csv-upload-summary", "children"),
    Output("heating-run-csv-inference", "disabled"),
    Input("heating-csv-upload", "contents"),
    State("heating-csv-upload", "filename"),
    prevent_initial_call=True,
)
def _handle_csv_upload(contents, filename):
    from haccp_dashboard.lib.csv_inference_panel import resolve_csv_upload_state
    upload_data, upload_children, status_panel, btn_disabled = resolve_csv_upload_state(contents, filename)
    return upload_data, upload_children, status_panel, btn_disabled


@callback(
    Output("heating-csv-inference-result", "children"),
    Input("heating-run-csv-inference", "n_clicks"),
    State("heating-csv-upload-store", "data"),
    prevent_initial_call=True,
)
def _run_csv_inference(n_clicks, upload_data):
    from haccp_dashboard.lib.csv_inference_panel import resolve_csv_inference_result
    return resolve_csv_inference_result(n_clicks, upload_data)



