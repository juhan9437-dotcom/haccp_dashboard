"""
HACCP 통합 요약보고서 – 페이지별 HTML 폼 빌더
각 페이지의 실시간 데이터를 불러와 종이 양식과 동일한 구조의 HTML 보고서를 반환합니다.
"""
from __future__ import annotations

import datetime
from dash import html

# ── 공통 스타일 ─────────────────────────────────────────────────────────────

_FORM_STYLE = {
    "fontFamily": "'Noto Sans KR', 'Apple SD Gothic Neo', sans-serif",
    "fontSize": "12px",
    "color": "#0f172a",
    "lineHeight": "1.5",
    "width": "100%",
}

_SECTION_HEADER = {
    "backgroundColor": "#dbeafe",
    "fontWeight": "700",
    "fontSize": "13px",
    "padding": "7px 12px",
    "borderTop": "2px solid #1e40af",
    "borderBottom": "1px solid #bfdbfe",
    "marginTop": "14px",
    "marginBottom": "0",
}

_TABLE_STYLE = {
    "width": "100%",
    "borderCollapse": "collapse",
    "marginBottom": "4px",
}

_TH = {
    "backgroundColor": "#eff6ff",
    "fontWeight": "700",
    "padding": "6px 8px",
    "border": "1px solid #cbd5e1",
    "textAlign": "center",
    "fontSize": "11px",
    "whiteSpace": "nowrap",
}

_TD = {
    "padding": "6px 8px",
    "border": "1px solid #cbd5e1",
    "textAlign": "center",
    "fontSize": "11px",
}

_KPI_GRID = {
    "display": "grid",
    "gridTemplateColumns": "repeat(4, 1fr)",
    "gap": "6px",
    "padding": "8px 0",
}

_KPI_CARD = {
    "border": "1px solid #cbd5e1",
    "borderRadius": "6px",
    "padding": "10px 8px",
    "textAlign": "center",
    "minHeight": "64px",
    "display": "flex",
    "flexDirection": "column",
    "justifyContent": "space-between",
}


def _risk_badge(level: str) -> html.Span:
    color_map = {
        "위험": ("#fef2f2", "#b91c1c", "#fecaca"),
        "경고": ("#fff7ed", "#b45309", "#fed7aa"),
        "정상": ("#f0fdf4", "#166534", "#bbf7d0"),
    }
    bg, text, border = color_map.get(level, ("#f8fafc", "#475569", "#e2e8f0"))
    return html.Span(
        level,
        style={
            "backgroundColor": bg,
            "color": text,
            "border": f"1px solid {border}",
            "borderRadius": "999px",
            "padding": "2px 10px",
            "fontWeight": "700",
            "fontSize": "11px",
        },
    )


def _form_header(title: str, subtitle: str, meta_rows: list[tuple]) -> html.Div:
    """작성일자/대상/승인자 등 상단 헤더 블록"""
    today = datetime.date.today().strftime("%Y-%m-%d")
    header_cells = [
        html.Th(label, style={**_TH, "width": f"{100//max(len(meta_rows),1)}%"})
        for label, _ in meta_rows
    ]
    value_cells = [
        html.Td(value or today if label == "작성일자" else value, style={**_TD, "minWidth": "60px"})
        for label, value in meta_rows
    ]
    return html.Div(
        [
            html.Div(
                [
                    html.Div(
                        "HACCP 통합 요약보고서",
                        style={"fontSize": "11px", "color": "#6b7280", "marginBottom": "2px"},
                    ),
                    html.Div(title, style={"fontSize": "20px", "fontWeight": "900", "color": "#0f172a"}),
                    html.Div(subtitle, style={"fontSize": "11px", "color": "#6b7280", "marginTop": "2px"}),
                ],
                style={"flex": "1"},
            ),
            html.Span(
                "요약보고서",
                style={
                    "backgroundColor": "#ef4444",
                    "color": "white",
                    "borderRadius": "6px",
                    "padding": "6px 14px",
                    "fontWeight": "800",
                    "fontSize": "13px",
                    "alignSelf": "flex-start",
                },
            ),
        ],
        style={"display": "flex", "justifyContent": "space-between", "alignItems": "flex-start", "marginBottom": "10px"},
    ), html.Div(
        html.Table(
            [html.Tr(header_cells), html.Tr(value_cells)],
            style=_TABLE_STYLE,
        )
    )


def _section(title: str, children) -> html.Div:
    return html.Div([html.Div(title, style=_SECTION_HEADER), children])


def _kpi_card(label: str, value: str, unit: str = "") -> html.Div:
    return html.Div(
        [
            html.Div(label, style={"fontSize": "11px", "color": "#6b7280", "fontWeight": "600"}),
            html.Div(value, style={"fontSize": "22px", "fontWeight": "900", "color": "#0f172a", "margin": "4px 0"}),
            html.Div(unit, style={"fontSize": "10px", "color": "#9ca3af"}),
        ],
        style=_KPI_CARD,
    )


def _empty_row(cols: int) -> html.Tr:
    return html.Tr([html.Td("–", style={**_TD, "color": "#9ca3af"}) for _ in range(cols)])


def _signature_row() -> html.Div:
    return html.Div(
        html.Table(
            [
                html.Tr([
                    html.Th("검토의견", style={**_TH, "width": "33%"}),
                    html.Th("작성자 서명", style={**_TH, "width": "33%"}),
                    html.Th("승인자 서명", style={**_TH, "width": "33%"}),
                ]),
                html.Tr([
                    html.Td("", style={**_TD, "height": "32px"}),
                    html.Td("", style=_TD),
                    html.Td("", style=_TD),
                ]),
            ],
            style=_TABLE_STYLE,
        ),
        style={"marginTop": "14px"},
    )


# ── 메인페이지 보고서 ────────────────────────────────────────────────────────

def build_main_report() -> html.Div:
    today = datetime.date.today().strftime("%Y-%m-%d")

    try:
        from haccp_dashboard.utils.state_manager import get_per_line_states
        line_states = get_per_line_states()
    except Exception:
        line_states = {}

    try:
        from haccp_dashboard.lib.dashboard_demo import (
            get_final_inspection_metrics,
            get_batch_summary_frame,
        )
        metrics = get_final_inspection_metrics("today")
        batch_frame = get_batch_summary_frame()
    except Exception:
        metrics = {}
        batch_frame = None

    # KPI 계산
    total_q = int(float(metrics.get("total_q_in", 0) or 0))
    ccp_dev = 0
    shipment_risk = 0
    unresolved_high = 0
    line_rows = []

    if batch_frame is not None and not batch_frame.empty:
        ccp_dev = int(batch_frame["hold_temp_ok"].eq(False).sum() + batch_frame["hold_time_ok"].eq(False).sum())
        shipment_risk = int(batch_frame["risk_level"].isin(["위험", "경고"]).sum())

    for line_id, s in sorted((line_states or {}).items()):
        risk = s.get("sensor_status") or s.get("risk_level") or "정상"
        line_rows.append(html.Tr([
            html.Td(f"라인 {line_id}", style=_TD),
            html.Td(s.get("batch_name", "–"), style=_TD),
            html.Td(s.get("stage_label", "–"), style=_TD),
            html.Td(_risk_badge(risk), style=_TD),
            html.Td("즉시조치 필요" if risk == "위험" else ("모니터링" if risk == "경고" else "–"), style=_TD),
            html.Td("QA 담당자", style=_TD),
        ]))
    if not line_rows:
        line_rows = [_empty_row(6)]

    # 라인별 HACCP 위험 요약
    hazard_rows = []
    for line_id, s in sorted((line_states or {}).items()):
        risk = s.get("sensor_status") or s.get("risk_level") or "정상"
        ccp_cnt = 0
        if not s.get("ccp_ok", True):
            ccp_cnt = 1
        hazard_rows.append(html.Tr([
            html.Td(f"라인 {line_id}", style=_TD),
            html.Td(str(ccp_cnt), style=_TD),
            html.Td("1" if risk in ("위험", "경고") else "0", style=_TD),
            html.Td(_risk_badge(risk), style=_TD),
            html.Td(s.get("ai_judgement", "–")[:30] if s.get("ai_judgement") else "–", style={**_TD, "textAlign": "left"}),
            html.Td("조치중" if risk != "정상" else "정상", style=_TD),
        ]))
    if not hazard_rows:
        hazard_rows = [_empty_row(6)]

    overall_risk = "정상"
    for s in (line_states or {}).values():
        if (s.get("sensor_status") or "") == "위험":
            overall_risk = "위험"
            break
        if (s.get("sensor_status") or "") == "경고":
            overall_risk = "경고"

    header_div, meta_table = _form_header(
        "메인페이지 요약 양식",
        "본 페이지는 공장의 현재 안전상태 및 HACCP 위험 현황을 신속하게 확인하기 위한 요약 보고서입니다.",
        [("작성일자", today), ("대상일자", today), ("작성자", "–"), ("승인자", "–"), ("교대", "–"), ("라인", "전체")],
    )

    return html.Div(
        [
            header_div,
            meta_table,
            _section("1. 핵심 KPI 요약", html.Div([
                _kpi_card("일일 총 생산량", str(total_q), "단위: 장"),
                _kpi_card("CCP 이탈 건수", str(ccp_dev), "단위: 건"),
                _kpi_card("출하 영향 배치 수", str(shipment_risk), "단위: 건"),
                _kpi_card("미조치 고위험 알람 수", str(unresolved_high), "단위: 건"),
            ], style=_KPI_GRID)),
            _section("2. 라인별 즉시조치 Batch 현황", html.Table(
                [
                    html.Tr([html.Th(c, style=_TH) for c in ["라인", "현재 Batch", "현재 공정", "위험등급", "즉시조치 필요", "담당자"]]),
                    *line_rows,
                ],
                style=_TABLE_STYLE,
            )),
            _section("3. 라인별 HACCP 위험 요약", html.Table(
                [
                    html.Tr([html.Th(c, style=_TH) for c in ["라인", "CCP 이탈 건수", "출하영향 건수", "현재상태\n(정상/경고/위험)", "주요 원인", "조치상태"]]),
                    *hazard_rows,
                ],
                style=_TABLE_STYLE,
            )),
            _section("4. 종합 판정 및 조치 메모", html.Table(
                [
                    html.Tr([html.Th("종합 판정", style={**_TH, "width": "35%"}), html.Th("조치/보고 메모", style=_TH)]),
                    html.Tr([
                        html.Td(_risk_badge(overall_risk), style={**_TD, "height": "48px"}),
                        html.Td("현재 공장 가동 중. 이상 감지 라인은 즉시 점검 바람.", style={**_TD, "textAlign": "left"}),
                    ]),
                ],
                style=_TABLE_STYLE,
            )),
            _signature_row(),
            html.Div(
                "※ 메인페이지는 QA/QC 담당자가 공장의 현재 위험 상태를 5초 안에 파악할 수 있도록 요약 작성한다.",
                style={"fontSize": "10px", "color": "#6b7280", "marginTop": "10px"},
            ),
        ],
        style=_FORM_STYLE,
    )


# ── 가열살균공정 보고서 ─────────────────────────────────────────────────────

def build_heating_report() -> html.Div:
    today = datetime.date.today().strftime("%Y-%m-%d")

    try:
        from haccp_dashboard.utils.state_manager import get_per_line_states
        line_states = get_per_line_states()
    except Exception:
        line_states = {}

    try:
        from haccp_dashboard.lib.dashboard_demo import get_batch_summary_frame
        batch_frame = get_batch_summary_frame()
    except Exception:
        batch_frame = None

    # CCP 통계
    ccp_dev_count = 0
    temp_ok_label = "적합"
    hold_ok_label = "적합"
    overall_ccp_risk = "정상"

    if batch_frame is not None and not batch_frame.empty:
        recent = batch_frame.head(6)
        temp_fails = int(recent["hold_temp_ok"].eq(False).sum())
        hold_fails = int(recent["hold_time_ok"].eq(False).sum())
        ccp_dev_count = temp_fails + hold_fails
        temp_ok_label = "이탈" if temp_fails > 0 else "적합"
        hold_ok_label = "이탈" if hold_fails > 0 else "적합"
        if ccp_dev_count > 0:
            overall_ccp_risk = "경고" if ccp_dev_count < 3 else "위험"

    # 실시간 모니터링 행
    monitoring_rows = []
    for line_id, s in sorted((line_states or {}).items()):
        peak_temp = s.get("peak_temp") or s.get("T") or 0.0
        hold_min = s.get("hold_minutes") or 0.0
        ccp_ok = s.get("ccp_ok", True)
        ccp_label = "적합" if ccp_ok else "이탈"
        monitoring_rows.append(html.Tr([
            html.Td(f"라인 {line_id}", style=_TD),
            html.Td(s.get("batch_name", "–"), style=_TD),
            html.Td(s.get("stage_label", "–"), style=_TD),
            html.Td(f"{float(peak_temp):.1f}°C", style=_TD),
            html.Td(f"{float(hold_min):.1f}분", style=_TD),
            html.Td(_risk_badge("정상" if ccp_ok else "경고"), style=_TD),
            html.Td("QA 담당자", style=_TD),
        ]))
    if not monitoring_rows:
        monitoring_rows = [_empty_row(7)]

    # 보조 지표 행
    aux_rows = []
    if batch_frame is not None and not batch_frame.empty:
        for _, row in batch_frame.head(3).iterrows():
            b_name = str(row.get("batch_name") or f"BATCH-{int(row.get('batch_id',0)):03d}")
            ph = float(row.get("final_ph", 0.0))
            risk = str(row.get("risk_level") or "정상")
            anomaly = "이상 없음" if risk == "정상" else ("pH 편차" if ph < 6.5 or ph > 7.0 else "온도 편차")
            aux_rows.append(html.Tr([
                html.Td(b_name, style=_TD),
                html.Td("–", style=_TD),
                html.Td("–", style=_TD),
                html.Td(f"{ph:.1f}", style=_TD),
                html.Td("–", style=_TD),
                html.Td(anomaly, style=_TD),
                html.Td(_risk_badge(risk), style={**_TD, "fontSize": "10px"}),
            ]))
    if not aux_rows:
        aux_rows = [_empty_row(7)]

    header_div, meta_table = _form_header(
        "가열살균공정 요약 양식",
        "본 페이지는 가열살균공정의 실시간 HACCP 상태 및 위험요인을 신속하게 요약하기 위한 보고서입니다.",
        [("작성일자", today), ("대상Batch", "현재 배치"), ("작성자", "–"), ("승인자", "–"), ("교대", "–"), ("라인", "전체")],
    )

    return html.Div(
        [
            header_div,
            meta_table,
            _section("1. 핵심 CCP 판정 요약", html.Div([
                _kpi_card("살균온도 판정", temp_ok_label, "기준: 72°C 이상"),
                _kpi_card("유지시간 판정", hold_ok_label, "기준: 15분 이상"),
                _kpi_card("CCP 이탈 Batch 수", str(ccp_dev_count), "단위: 건"),
                _kpi_card("현재 위험 상태", overall_ccp_risk, "상태: 정상/경고/위험"),
            ], style=_KPI_GRID)),
            _section("2. 실시간 공정 모니터링", html.Table(
                [
                    html.Tr([html.Th(c, style=_TH) for c in ["라인", "현재 Batch", "현재 공정단계", "살균온도", "유지시간", "CCP 판정", "담당자"]]),
                    *monitoring_rows,
                ],
                style=_TABLE_STYLE,
            )),
            _section("3. 보조 지표 및 품질 이상징후", html.Table(
                [
                    html.Tr([html.Th(c, style=_TH) for c in ["Batch", "유량", "압력", "pH", "점도/전기전도도", "이상징후", "AI 요약"]]),
                    *aux_rows,
                ],
                style=_TABLE_STYLE,
            )),
            _section("4. 완료 Batch 비교 및 개선조치", html.Table(
                [
                    html.Tr([html.Th("완료 Batch 비교 요약", style={**_TH, "width": "40%"}), html.Th("개선조치 / 보고 메모", style=_TH)]),
                    html.Tr([
                        html.Td(f"최근 배치 CCP 이탈 {ccp_dev_count}건", style={**_TD, "height": "48px"}),
                        html.Td("이탈 배치 원인 점검 및 재가열 여부 확인 필요", style={**_TD, "textAlign": "left"}),
                    ]),
                ],
                style=_TABLE_STYLE,
            )),
            _signature_row(),
            html.Div(
                "※ 살균온도·유지시간은 핵심 CCP로 판정하고, 유량·압력은 공정 안정성 감시, pH·점도는 품질 및 오염 이상징후 확인용으로 기록한다.",
                style={"fontSize": "10px", "color": "#6b7280", "marginTop": "10px"},
            ),
        ],
        style=_FORM_STYLE,
    )


# ── 최종제품검사 보고서 ──────────────────────────────────────────────────────

def build_final_inspection_report() -> html.Div:
    today = datetime.date.today().strftime("%Y-%m-%d")

    try:
        from haccp_dashboard.lib.dashboard_demo import (
            get_final_inspection_metrics,
            get_final_product_batch_summary_frame,
            get_final_inspection_batch_round_summary,
            get_configured_runs_per_day,
        )
        metrics = get_final_inspection_metrics("today")
        batch_summary = get_final_product_batch_summary_frame()
        rounds_total = get_configured_runs_per_day()
        point_summary = get_final_inspection_batch_round_summary("today", batch_count=3, rounds=rounds_total)
    except Exception:
        metrics = {}
        batch_summary = None
        point_summary = []

    try:
        from haccp_dashboard.lib.main_helpers import get_dashboard_current_lot_index
        current_lot = int(get_dashboard_current_lot_index())
    except Exception:
        current_lot = None

    total_q = int(float(metrics.get("total_q_in", 0) or 0))
    pass_count = 0
    fail_count = 0
    pending_count = 0

    if batch_summary is not None and not batch_summary.empty:
        pass_count = int(batch_summary["shipment_ok"].eq(True).sum())
        fail_count = int(batch_summary["risk_level"].eq("위험").sum())
        pending_count = int(current_lot is not None)

    # 라인별 검사 현황
    seen_lines: dict[int, dict] = {}
    for item in (point_summary or []):
        lid = int(item.get("line_id", 0))
        if lid and lid not in seen_lines:
            seen_lines[lid] = item

    line_inspect_rows = []
    for lid in sorted(seen_lines):
        item = seen_lines[lid]
        risk = item.get("risk_level") or "정상"
        is_pending = current_lot is not None and int(item.get("round", 0)) >= int(current_lot)
        line_inspect_rows.append(html.Tr([
            html.Td(f"라인 {lid}", style=_TD),
            html.Td(item.get("batch_name") or "–", style=_TD),
            html.Td(item.get("round_time_label") or "–", style=_TD),
            html.Td("CNN 이미지", style=_TD),
            html.Td("검사 대기" if is_pending else (_risk_badge(risk)), style=_TD),
            html.Td(_risk_badge(risk), style=_TD),
            html.Td("가능" if risk == "정상" else "보류", style=_TD),
        ]))
    if not line_inspect_rows:
        line_inspect_rows = [_empty_row(7)]

    # Batch별 AI 분석
    ai_rows = []
    if batch_summary is not None and not batch_summary.empty:
        for _, row in batch_summary.head(3).iterrows():
            b_name = str(row.get("batch_name") or "–")
            risk = str(row.get("risk_level") or "정상")
            suspect = int(float(row.get("suspect_count", 0) or 0))
            confirmed = int(float(row.get("confirmed_nonconforming_count", 0) or 0))
            ai_label = "정상" if risk == "정상" else ("물 혼합 의심" if risk == "경고" else "복합 혼입")
            ai_rows.append(html.Tr([
                html.Td(b_name, style=_TD),
                html.Td(ai_label, style=_TD),
                html.Td("있음" if suspect > 0 else "없음", style=_TD),
                html.Td("pH 편차" if risk != "정상" else "없음", style=_TD),
                html.Td("–", style=_TD),
                html.Td(_risk_badge(risk), style={**_TD, "fontSize": "10px"}),
            ]))
    if not ai_rows:
        ai_rows = [_empty_row(6)]

    overall = "위험" if fail_count > 0 else ("경고" if pending_count > 0 else "정상")

    header_div, meta_table = _form_header(
        "최종제품검사 요약 양식",
        "본 페이지는 최종제품의 검사 현황, AI 이미지 분석 결과, 출하 결정 내역을 종합적으로 요약하는 보고서입니다.",
        [("작성일자", today), ("대상일자", today), ("작성자", "–"), ("승인자", "–"), ("교대", "–"), ("라인", "전체")],
    )

    return html.Div(
        [
            header_div,
            meta_table,
            _section("1. 검사 KPI 요약", html.Div([
                _kpi_card("총 검사건수", str(total_q), "단위: 건"),
                _kpi_card("합격 Batch 수", str(pass_count), "단위: 건"),
                _kpi_card("부적합 Batch 수", str(fail_count), "단위: 건"),
                _kpi_card("검사대기 Batch 수", str(pending_count), "단위: 건"),
            ], style=_KPI_GRID)),
            _section("2. 라인별 검사 현황", html.Table(
                [
                    html.Tr([html.Th(c, style=_TH) for c in ["라인", "대상 Batch", "검사시각", "검사방식", "AI 판독결과", "최종 판정", "출하 여부"]]),
                    *line_inspect_rows,
                ],
                style=_TABLE_STYLE,
            )),
            _section("3. Batch별 AI 분석 요약", html.Table(
                [
                    html.Tr([html.Th(c, style=_TH) for c in ["Batch", "이미지 판독결과", "물 혼합 의심", "주요 이상징후", "신뢰도", "비고"]]),
                    *ai_rows,
                ],
                style=_TABLE_STYLE,
            )),
            _section("4. 최종 판정 및 출하 조치", html.Table(
                [
                    html.Tr([html.Th("최종 판정", style={**_TH, "width": "35%"}), html.Th("출하 / 재검 / 보류 조치", style=_TH)]),
                    html.Tr([
                        html.Td(_risk_badge(overall), style={**_TD, "height": "48px"}),
                        html.Td(
                            "전 라인 이상 없음 – 출하 가능" if overall == "정상"
                            else ("부적합 배치 출하 보류 및 격리 후 원인 조사 필요" if overall == "위험"
                                  else "의심 샘플 재검 확정 후 출하 여부 결정"),
                            style={**_TD, "textAlign": "left"},
                        ),
                    ]),
                ],
                style=_TABLE_STYLE,
            )),
            _signature_row(),
            html.Div(
                "※ 최종제품검사는 비파괴 이미지 분석과 검사 결과를 종합하여 합격·부적합·재검 여부 및 출하 가능 여부를 기록한다.",
                style={"fontSize": "10px", "color": "#6b7280", "marginTop": "10px"},
            ),
        ],
        style=_FORM_STYLE,
    )


# ── 알람이력 보고서 ──────────────────────────────────────────────────────────

def build_alarm_history_report() -> html.Div:
    today = datetime.date.today().strftime("%Y-%m-%d")

    try:
        from haccp_dashboard.lib.dashboard_demo import get_batch_summary_frame, get_final_product_batch_summary_frame
        batch_frame = get_batch_summary_frame()
        final_frame = get_final_product_batch_summary_frame()
    except Exception:
        batch_frame = None
        final_frame = None

    # KPI
    total_alarms = 0
    high_unresolved = 0
    resolved = 0
    avg_time_min = "–"

    active_alarm_rows = []
    history_rows = []

    if batch_frame is not None and not batch_frame.empty:
        danger_batches = batch_frame[batch_frame["risk_level"] == "위험"].head(4)
        warn_batches = batch_frame[batch_frame["risk_level"] == "경고"].head(4)
        all_alarms = list(danger_batches.itertuples()) + list(warn_batches.itertuples())
        total_alarms = len(all_alarms)
        high_unresolved = len(danger_batches)
        resolved = total_alarms - high_unresolved

        import datetime as dt
        base_time = dt.datetime.combine(dt.date.today(), dt.time(4, 0))
        for idx, row in enumerate(all_alarms[:5]):
            alarm_time = (base_time + dt.timedelta(hours=idx * 2)).strftime("%H:%M")
            level = str(row.risk_level) if hasattr(row, "risk_level") else "경고"
            b_name = str(row.batch_name) if hasattr(row, "batch_name") else "–"
            alarm_type = "CCP 이탈" if level == "위험" else "품질 경고"
            status = "미해결" if level == "위험" else "처리중"
            active_alarm_rows.append(html.Tr([
                html.Td(alarm_time, style=_TD),
                html.Td(b_name, style=_TD),
                html.Td(alarm_type, style=_TD),
                html.Td(_risk_badge(level), style=_TD),
                html.Td("QA 담당자", style=_TD),
                html.Td(status, style=_TD),
            ]))
        for idx, row in enumerate(all_alarms[:4]):
            level = str(row.risk_level) if hasattr(row, "risk_level") else "경고"
            b_name = str(row.batch_name) if hasattr(row, "batch_name") else "–"
            recur = "재발 없음" if idx % 2 == 0 else "재발 있음"
            capa = "진행중" if level == "위험" else "완료"
            history_rows.append(html.Tr([
                html.Td(f"ALM-{idx+1:03d}", style=_TD),
                html.Td("CCP 이탈" if level == "위험" else "품질 이상", style=_TD),
                html.Td(str(idx + 1), style=_TD),
                html.Td(today, style=_TD),
                html.Td(recur, style=_TD),
                html.Td(capa, style=_TD),
            ]))

    if not active_alarm_rows:
        active_alarm_rows = [_empty_row(6)]
    if not history_rows:
        history_rows = [_empty_row(6)]

    header_div, meta_table = _form_header(
        "알람이력 관리 요약 양식",
        "본 페이지는 알람 발생, 대응 상태, 재발 이력을 체계적으로 관리하기 위한 요약 보고서입니다.",
        [("작성일자", today), ("대상일자", today), ("작성자", "–"), ("승인자", "–"), ("교대", "–"), ("라인", "전체")],
    )

    return html.Div(
        [
            header_div,
            meta_table,
            _section("1. 알람 KPI 요약", html.Div([
                _kpi_card("전체 알람 건수", str(total_alarms), "단위: 건"),
                _kpi_card("미조치 고위험", str(high_unresolved), "단위: 건"),
                _kpi_card("조치 완료 건수", str(resolved), "단위: 건"),
                _kpi_card("평균 조치시간", avg_time_min, "단위: 분"),
            ], style=_KPI_GRID)),
            _section("2. 현재 활성 알람 현황", html.Table(
                [
                    html.Tr([html.Th(c, style=_TH) for c in ["발생시각", "라인 / Batch", "알람유형", "심각도", "담당자", "조치상태"]]),
                    *active_alarm_rows,
                ],
                style=_TABLE_STYLE,
            )),
            _section("3. 전체 알람 이력 및 재발 여부", html.Table(
                [
                    html.Tr([html.Th(c, style=_TH) for c in ["알람 ID", "주요 원인", "발생횟수", "최근 발생시각", "재발 여부", "CAPA 상태"]]),
                    *history_rows,
                ],
                style=_TABLE_STYLE,
            )),
            _section("4. 선택 알람 상세 및 조치 메모", html.Table(
                [
                    html.Tr([html.Th("원인 분석", style={**_TH, "width": "40%"}), html.Th("시정·예방조치 및 확인", style=_TH)]),
                    html.Tr([
                        html.Td("CCP 이탈 시 즉각 공정 중단 필요" if high_unresolved > 0 else "현재 이탈 없음", style={**_TD, "height": "48px", "textAlign": "left"}),
                        html.Td("재가열 또는 출하 보류 후 QA 재확인" if high_unresolved > 0 else "모니터링 유지", style={**_TD, "textAlign": "left"}),
                    ]),
                ],
                style=_TABLE_STYLE,
            )),
            _signature_row(),
            html.Div(
                "※ 알람이력 페이지는 이상 발생부터 조치 완료까지의 흐름과 재발 여부를 추적할 수 있도록 기록한다.",
                style={"fontSize": "10px", "color": "#6b7280", "marginTop": "10px"},
            ),
        ],
        style=_FORM_STYLE,
    )


# ── 라우터 ───────────────────────────────────────────────────────────────────

def build_report_for_path(pathname: str) -> tuple[html.Div, str]:
    """pathname → (report_html, modal_title)"""
    path = (pathname or "/").rstrip("/") or "/"
    if path == "/heating":
        return build_heating_report(), "가열살균공정 요약 보고서"
    if path == "/final-inspection":
        return build_final_inspection_report(), "최종제품검사 요약 보고서"
    if path == "/alarm-history":
        return build_alarm_history_report(), "알람이력 관리 요약 보고서"
    return build_main_report(), "메인페이지 요약 보고서"
