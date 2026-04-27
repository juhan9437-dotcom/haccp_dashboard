import dash
from dash import ALL, Input, Output, State, callback, ctx, dcc, html, no_update
from functools import lru_cache

from haccp_dashboard.components.status_badges import (
    kpi_card as _kpi_card,
    kpi_row as _kpi_row,
)


dash.register_page(__name__, path="/alarm-history")


def _make_badge(label: str, tone: str):
    from haccp_dashboard.lib import dashboard_demo as demo

    return demo.make_badge(label, tone)

_OWNER_PROFILES = [
    {"name": "박주한", "role": "공정 분석가", "department": "공정분석팀", "phone": "010-1111-2222", "email": "juhan.park@haccp.local"},
    {"name": "남동현", "role": "품질 관리자", "department": "품질관리팀", "phone": "010-2222-3333", "email": "donghyun.nam@haccp.local"},
    {"name": "권어진", "role": "생산 엔지니어", "department": "생산기술팀", "phone": "010-3333-4444", "email": "eojin.kwon@haccp.local"},
    {"name": "서채은", "role": "품질 분석가", "department": "품질분석팀", "phone": "010-4444-5555", "email": "chaeun.seo@haccp.local"},
    {"name": "조윤주", "role": "미생물 검사 담당", "department": "미생물검사팀", "phone": "010-5555-6666", "email": "yunju.jo@haccp.local"},
    {"name": "양병희", "role": "설비 관리자", "department": "설비관리팀", "phone": "010-6666-7777", "email": "byeonghui.yang@haccp.local"},
]


@lru_cache(maxsize=1)
def _heating_summary():
    from haccp_dashboard.lib import dashboard_demo as demo

    return demo.get_batch_summary_frame().sort_values(["date", "batch_id"], ascending=[False, False]).copy()


@lru_cache(maxsize=1)
def _final_summary():
    from haccp_dashboard.lib import dashboard_demo as demo

    return demo.get_final_product_batch_summary_frame().sort_values(["date", "batch_id"], ascending=[False, False]).copy()


def _assign_owner(index: int) -> dict:
    return dict(_OWNER_PROFILES[index % len(_OWNER_PROFILES)])


def _resolve_alert_level(risk_level: str, allow_normal: bool = False, sequence_index: int = 0) -> str:
    if risk_level == "위험":
        return "위험"
    if allow_normal and sequence_index % 2 == 1:
        return "정상"
    return "경고"


def _build_alert_row(row_id: str, level: str, time: str, dataset: str, alert_type: str, message: str, status: str, owner: dict):
    return {
        "id": row_id,
        "level": level,
        "time": time,
        "dataset": dataset,
        "type": alert_type,
        "message": message,
        "status": status,
        "owner_name": owner["name"],
        "owner_role": owner["role"],
        "owner_department": owner["department"],
        "owner_phone": owner["phone"],
        "owner_email": owner["email"],
    }


def _build_heating_alert_rows():
    rows = []
    heating_summary = _heating_summary()
    for index, row in enumerate(heating_summary.head(8).itertuples()):
        level = _resolve_alert_level(row.risk_level)
        if level == "위험":
            status = "미해결" if index % 3 != 2 else "확인완료"
        else:
            status = "처리중" if index % 2 == 0 else "확인완료"
        owner = _assign_owner(index)
        rows.append(
            _build_alert_row(
                row_id=f"heating-{index + 1}",
                level=level,
                time=row.end_time.strftime("%Y-%m-%d %H:%M"),
                dataset="우유공정 데이터셋",
                alert_type="가열살균",
                message=f"{row.batch_name} 살균 {row.peak_temp:.1f}℃ / 냉각 {row.final_temp:.1f}℃ / 안정도 {row.stability_score:.1f}%",
                status=status,
                owner=owner,
            )
        )
    return rows


def _build_final_alert_rows():
    rows = []
    heating_summary = _heating_summary()
    final_summary = _final_summary()
    offset = len(heating_summary.head(8))
    for index, row in enumerate(final_summary.head(8).itertuples()):
        level = _resolve_alert_level(row.risk_level, allow_normal=True, sequence_index=offset + index)
        if level == "위험":
            status = "미해결" if index % 2 == 0 else "확인완료"
        elif level == "정상":
            status = "확인완료"
        else:
            status = "미처리" if index % 3 == 0 else "확인완료"
        owner = _assign_owner(offset + index)
        rows.append(
            _build_alert_row(
                row_id=f"final-{index + 1}",
                level=level,
                time=f"{row.date} 18:00",
                dataset="이미지 검사 데이터셋",
                alert_type="최종품질",
                message=f"{row.batch_name} pH {row.final_ph:.2f} / 최종온도 {row.final_temp:.1f}℃ / 판정 {row.status}",
                status=status,
                owner=owner,
            )
        )
    return rows


def _build_alert_rows():
    # Prefer cumulative DB-backed alert log (realistic operations history).
    try:
        from haccp_dashboard.db_store import list_alert_events

        events = list_alert_events(limit=160)
        rows = []
        for index, event in enumerate(events):
            level = str(event.get("level") or "정보")
            occurred_at = str(event.get("occurred_at") or event.get("occurred_at") or event.get("meta", {}).get("time_iso") or "")
            time_label = occurred_at.replace("T", " ")[:16] if occurred_at else "-"

            event_type = str(event.get("event_type") or "")
            dataset = "센서/가열 공정" if not event_type.startswith("final") else "최종제품공정(이미지)"
            status = str(event.get("status") or ("미해결" if level == "위험" else "처리중" if level == "경고" else "확인완료"))
            owner = _assign_owner(index)

            rows.append(
                _build_alert_row(
                    row_id=str(event.get("id") or f"db-{index}"),
                    level=level,
                    time=time_label,
                    dataset=dataset,
                    alert_type=event_type or "event",
                    message=str(event.get("message") or ""),
                    status=status,
                    owner=owner,
                )
            )
        if rows:
            return rows
    except Exception:
        pass

    rows = _build_heating_alert_rows() + _build_final_alert_rows()
    return sorted(rows, key=lambda item: item["time"], reverse=True)

@lru_cache(maxsize=1)
def _all_alert_rows():
    return _build_alert_rows()


@lru_cache(maxsize=1)
def _alert_row_by_id():
    rows = _all_alert_rows()
    return {row["id"]: row for row in rows}


def _alert_counts(rows: list[dict]):
    rows = rows or []
    return {
        "total": len(rows),
        "danger": sum(1 for row in rows if row.get("level") == "위험"),
        "warning": sum(1 for row in rows if row.get("level") == "경고"),
        "unresolved": sum(1 for row in rows if row.get("status") == "미해결"),
    }


def _default_alert_row_id(tab_value: str) -> str | None:
    rows = _filter_alert_rows(tab_value)
    if not rows:
        return None
    return rows[0]["id"]


def _filter_alert_rows(tab_value: str):
    all_rows = _all_alert_rows()
    if tab_value == "open":
        return [row for row in all_rows if row.get("status") == "미해결"]
    return list(all_rows)


def _owner_link(row):
    return html.Button(
        row["owner_name"],
        id={"type": "alarm-owner-link", "index": row["id"]},
        n_clicks=0,
        className="alarm-owner-link",
    )


def _row_style(is_selected: bool):
    return {
        "borderBottom": "1px solid #f3f4f6",
        "background": "#eff6ff" if is_selected else "white",
        "boxShadow": "inset 3px 0 0 #1565c0" if is_selected else "none",
        "transition": "background 0.18s ease, box-shadow 0.18s ease",
    }


def _table_header():
    return html.Thead(
        html.Tr(
            [
                html.Th("구분", style={"width": "10%"}),
                html.Th("일시", style={"padding": "10px", "width": "16%"}),
                html.Th("데이터셋", style={"width": "16%"}),
                html.Th("유형", style={"width": "12%"}),
                html.Th("내용", style={"width": "28%"}),
                html.Th("상태", style={"width": "10%"}),
                html.Th("담당", style={"width": "8%"}),
            ],
            style={"color": "#64748b", "borderBottom": "1px solid #dde3ec",
                   "fontSize": "12px", "fontWeight": "700",
                   "background": "#f8fafc"},
        )
    )


def _table_rows(rows, selected_row_id=None):
    return html.Tbody(
        [
            html.Tr(
                [
                    html.Td(_make_badge(row["level"], row["level"]), style={"padding": "15px 0"}),
                    html.Td(row["time"]),
                    html.Td(row["dataset"]),
                    html.Td(row["type"]),
                    html.Td(row["message"], style={"textAlign": "left", "padding": "12px 10px"}),
                    html.Td(_make_badge(row["status"], row["status"])),
                    html.Td(_owner_link(row)),
                ],
                style=_row_style(row["id"] == selected_row_id),
            )
            for row in rows
        ]
    )


def _build_alarm_table(rows, selected_row_id=None):
    return html.Table(
        style={"width": "100%", "textAlign": "center", "fontSize": "12px", "tableLayout": "fixed"},
        children=[_table_header(), _table_rows(rows, selected_row_id=selected_row_id)],
    )


def _detail_value(label, value, accent="#0f172a"):
    return html.Div(
        [
            html.Div(label, className="ds-detail-label"),
            html.Div(value, className="ds-detail-val", style={"color": accent}),
        ],
        className="ds-detail-cell",
    )


def _timeline_item(title, caption, tone="info"):
    palette = {
        "info":    ("#dbeafe", "#1565c0"),
        "warning": ("#fde68a", "#b45309"),
        "danger":  ("#fecaca", "#b91c1c"),
        "success": ("#bbf7d0", "#15803d"),
    }
    dot_bg, text_color = palette[tone]
    return html.Div(
        [
            html.Div(className="ds-timeline-dot",
                      style={"background": dot_bg, "borderColor": text_color}),
            html.Div(
                [
                    html.Div(title, className="ds-timeline-title"),
                    html.Div(caption, className="ds-timeline-caption"),
                ],
                style={"flex": 1},
            ),
        ],
        className="ds-timeline-item",
    )


def _derive_alert_detail(row):
    is_heating = row["type"] == "가열살균"
    is_danger = row["level"] == "위험"

    if is_heating:
        hazard_type = "생물학적 위해"
        process = "가열살균 > Hold"
        ccp_text = "CCP"
        critical_limit = "CCP(보온 온도/시간) 임계한계 충족 여부"
        actual_value = row["message"]
        shipment_impact = "출하 보류 후 재확인 필요" if is_danger else "추가 확인 후 조건부 진행 가능"
        immediate_action = "해당 배치 격리 후 살균 온도/보온 시간 로그를 재검토합니다."
        root_cause = "센서 편차, Hold 구간 체류시간 부족, 열교환 효율 저하 가능성을 우선 점검합니다."
        preventive_action = "센서 교정, Hold 구간 설정값 재점검, 동일 설비 직전 배치 비교를 수행합니다."
        verification = "재측정 결과와 최종검사 결과를 함께 확인한 뒤 QA가 출하 가능 여부를 승인합니다."
    else:
        hazard_type = "화학/미생물 품질 위해"
        process = "최종품질 > 출하판정"
        ccp_text = "CP"
        critical_limit = "배치 출하판정 기준(적합/보류/부적합) 충족 여부"
        actual_value = row["message"]
        shipment_impact = "출하 차단 후 재검사 필요" if is_danger else "재검사 전 출하 보류 권고"
        immediate_action = "의심 샘플을 분리 보관하고 동일 배치의 검사 포인트를 재확인합니다."
        root_cause = "시료 혼입, 냉각 미달, 검사 구간 편차 또는 세정 잔류 가능성을 검토합니다."
        preventive_action = "샘플링 기준 재점검, 라인 세정 상태 확인, 반복 불량 구간을 주간 단위로 검증합니다."
        verification = "재검사 PASS 여부와 공정 이력 정합성을 확인한 뒤 QA 최종 판정을 기록합니다."

    status_text = row["status"]
    if status_text in {"미해결", "미처리"}:
        current_state = "발생 / 격리조치 필요"
        verification_result = "검증 대기"
        timeline = [
            ("알람 발생", f"{row['time']} 기준 이상 신호가 기록되었습니다.", "danger" if is_danger else "warning"),
            ("담당자 지정", f"현재 담당자는 {row['owner_name']} {row['owner_role']}입니다.", "info"),
            ("즉시 조치 필요", immediate_action, "warning"),
            ("QA 검토 대기", shipment_impact, "info"),
        ]
    elif status_text == "처리중":
        current_state = "원인조사 / 시정조치 진행중"
        verification_result = "재검증 진행중"
        timeline = [
            ("알람 접수", f"{row['time']} 알람이 접수되었습니다.", "warning"),
            ("현장 확인", f"{row['owner_name']} 담당자가 공정 상태를 확인 중입니다.", "info"),
            ("시정조치 진행", preventive_action, "warning"),
            ("재검증 예정", verification, "info"),
        ]
    else:
        current_state = "조치 완료 / QA 확인완료"
        verification_result = "검증 완료"
        timeline = [
            ("알람 접수", f"{row['time']} 알람이 기록되었습니다.", "warning" if not is_danger else "danger"),
            ("현장 조치", immediate_action, "info"),
            ("재검증 완료", verification, "success"),
            ("종결", f"상태가 {row['status']}로 기록되었고 출하 영향 여부를 함께 검토했습니다.", "success"),
        ]

    return {
        "hazard_type": hazard_type,
        "process": process,
        "ccp_text": ccp_text,
        "critical_limit": critical_limit,
        "actual_value": actual_value,
        "shipment_impact": shipment_impact,
        "current_state": current_state,
        "immediate_action": immediate_action,
        "root_cause": root_cause,
        "preventive_action": preventive_action,
        "verification": verification,
        "verification_result": verification_result,
        "timeline": timeline,
    }


def _build_alert_detail_section(row):
    if not row:
        return html.Div(
            "선택한 알람이 없습니다.",
            style={"padding": "28px 20px", "fontSize": "13px", "color": "#64748b", "textAlign": "center"},
        )

    detail = _derive_alert_detail(row)
    return html.Div(
        [
            html.Div(
                [
                    html.Div(
                        [
                            html.Div("선택 알람 상세", className="ds-card-title"),
                            html.Div("알람 이력 표에서 선택한 건의 상세 정보와 처리 현황입니다.",
                                      className="ds-card-sub"),
                        ]
                    ),
                    _make_badge(row["level"], row["level"]),
                ],
                style={"display": "flex", "justifyContent": "space-between",
                       "alignItems": "flex-start", "marginBottom": "14px"},
            ),
            html.Div(
                [
                    html.Div(
                        [
                            html.Div("알람 상세", className="ds-section-header",
                                      style={"marginBottom": "12px"}),
                            html.Div(
                                [
                                    _detail_value("유형", row["type"]),
                                    _detail_value("위해 유형", detail["hazard_type"], "#b45309" if row["level"] != "정상" else "#166534"),
                                    _detail_value("공정 단계", detail["process"]),
                                    _detail_value("관리점", detail["ccp_text"], "#1d4ed8"),
                                    _detail_value("한계기준", detail["critical_limit"]),
                                    _detail_value("실제값", detail["actual_value"], "#991b1b" if row["level"] == "위험" else "#334155"),
                                    _detail_value("출하 영향", detail["shipment_impact"], "#dc2626" if row["status"] in {"미해결", "미처리"} else "#166534"),
                                    _detail_value("담당자", f"{row['owner_name']} · {row['owner_role']}"),
                                ],
                                className="alarm-detail-value-grid",
                            ),
                        ],
                        className="alarm-detail-panel",
                    ),
                    html.Div(
                        [
                            html.Div("처리 현황", className="ds-section-header",
                                      style={"marginBottom": "12px"}),
                            html.Div(
                                [
                                    _detail_value("현재 상태", detail["current_state"], "#2563eb"),
                                    _detail_value("검증 상태", detail["verification_result"], "#166534" if detail["verification_result"] == "검증 완료" else "#b45309"),
                                ],
                                className="alarm-status-top-grid",
                            ),
                            _detail_value("즉시 조치", detail["immediate_action"]),
                            html.Div(style={"height": "10px"}),
                            _detail_value("원인 분석", detail["root_cause"]),
                            html.Div(style={"height": "10px"}),
                            _detail_value("재발 방지", detail["preventive_action"]),
                            html.Div(style={"height": "10px"}),
                            _detail_value("검증 및 승인", detail["verification"]),
                        ],
                        className="alarm-status-panel",
                    ),
                ],
                className="alarm-detail-grid",
            ),
            html.Div(
                [
                    html.Div("처리 타임라인", className="ds-section-header",
                               style={"marginBottom": "12px"}),
                    html.Div(
                        [_timeline_item(title, caption, tone) for title, caption, tone in detail["timeline"]],
                        className="alarm-timeline-grid",
                    ),
                ],
                style={"marginTop": "14px", "padding": "16px",
                       "border": "1px solid #dde3ec", "borderRadius": "12px",
                       "background": "white"},
            ),
        ]
    )


def _owner_modal_body(row):
    if not row:
        return html.Div("담당자 정보를 찾을 수 없습니다.",
                        style={"fontSize": "13px", "color": "#64748b"})
    return html.Div(
        [
            html.Div(row["owner_name"],
                      style={"fontSize": "22px", "fontWeight": "800", "color": "#0f172a", "marginBottom": "8px"}),
            html.Div(row["owner_role"],
                      style={"fontSize": "14px", "color": "#475569", "marginBottom": "10px"}),
            html.Div(row["owner_department"],
                      style={"fontSize": "13px", "fontWeight": "700", "color": "#1565c0", "marginBottom": "10px"}),
            html.Div(
                [
                    html.Div("전화번호", className="ds-modal-info-label"),
                    html.Div(row["owner_phone"], className="ds-modal-info-val"),
                ],
                className="ds-modal-info-cell",
            ),
            html.Div(
                [
                    html.Div("이메일", className="ds-modal-info-label"),
                    html.Div(row["owner_email"], className="ds-modal-info-val"),
                ],
                className="ds-modal-info-cell",
            ),
        ]
    )


def layout():
    all_rows = _all_alert_rows()
    counts = _alert_counts(all_rows)

    # 해결률 및 평균 처리 시간 계산
    resolved = sum(1 for r in all_rows if r.get("status") == "확인완료")
    total = max(counts["total"], 1)
    resolution_rate = f"{resolved / total * 100:.0f}%"

    # KPI 카드 함수 (전 페이지 공통 컴포넌트 사용)
    def _kpi(title, value, accent="#374151", description=""):
        return _kpi_card(title, value, description)

    return html.Div(
        [
            dcc.Store(
                id="alarm-ui-state",
                data={
                    "selected_row_id": _default_alert_row_id("open"),
                    "modal_open": False,
                    "modal_row_id": None,
                },
            ),
            html.Div(
                [
                    html.Div(
                        [
                            html.H2("알람 이력 관리", className="section-title page"),
                            _kpi_row(
                                [
                                    _kpi("총 알람", f"{counts['total']}", description="누적 알람 총 건수"),
                                    _kpi("위험", f"{counts['danger']}", description="즉시 조치 필요 위험 알람"),
                                    _kpi("경고", f"{counts['warning']}", description="모니터링 강화 필요 경고"),
                                    _kpi("미처리", f"{counts['unresolved']}", description="확인·조치 미완료 알람"),
                                ]
                            ),
                        ],
                        className="screen-zone top",
                    ),
                    html.Div(
                        [
                            html.Div(
                                [
                                    html.H3("알람 이력", className="section-title"),
                                    dcc.Tabs(
                                        id="alarm-history-tabs",
                                        value="open",
                                        className="compact-tabs alarm-history-tabs",
                                        children=[
                                            dcc.Tab(label="미해결", value="open", className="alarm-history-tab", selected_className="alarm-history-tab--selected"),
                                            dcc.Tab(label="전체", value="all", className="alarm-history-tab", selected_className="alarm-history-tab--selected"),
                                        ],
                                    ),
                                    html.Div(
                                        id="alarm-history-table-shell",
                                        className="compact-scroll",
                                        children=_build_alarm_table(_filter_alert_rows("open"), _default_alert_row_id("open")),
                                    ),
                                ],
                                className="screen-zone middle chart-box",
                            ),
                             html.Div(
                                 id="alarm-detail-shell",
                                 children=_build_alert_detail_section(_alert_row_by_id().get(_default_alert_row_id("open"))),
                                 className="screen-zone bottom chart-box",
                             ),
                        ],
                    ),
                ],
                className="dashboard-container dashboard-screen",
            ),
            html.Div(
                id="alarm-owner-modal",
                style={"display": "none"},
                children=[
                    html.Div(className="ds-modal-overlay"),
                    html.Div(
                        [
                            html.Div(
                                [
                                    html.Div("담당자 정보", className="ds-modal-title"),
                                    html.Button(
                                        "닫기",
                                        id="alarm-owner-modal-close",
                                        n_clicks=0,
                                        className="ds-modal-close",
                                    ),
                                ],
                                className="ds-modal-header",
                            ),
                            html.Div(id="alarm-owner-modal-body", children=_owner_modal_body(None)),
                        ],
                        className="ds-modal-box",
                    ),
                ],
            ),
        ],
        style={"height": "100%", "padding": "0"},
    )


@callback(
    Output("alarm-ui-state", "data"),
    Input("url", "pathname"),
    Input("alarm-history-tabs", "value"),
    Input({"type": "alarm-owner-link", "index": ALL}, "n_clicks"),
    Input("alarm-owner-modal-close", "n_clicks"),
    State("alarm-ui-state", "data"),
)
def update_alarm_ui_state(pathname, tab_value, _owner_clicks, _close_clicks, ui_state):
    ui_state = dict(ui_state or {})
    ui_state.setdefault("selected_row_id", _default_alert_row_id(tab_value))
    ui_state.setdefault("modal_open", False)
    ui_state.setdefault("modal_row_id", None)

    triggered = ctx.triggered_id
    filtered_rows = _filter_alert_rows(tab_value)
    filtered_ids = {row["id"] for row in filtered_rows}

    if pathname != "/alarm-history":
        return ui_state

    if triggered == "url":
        return {
            "selected_row_id": _default_alert_row_id(tab_value),
            "modal_open": False,
            "modal_row_id": None,
        }

    if triggered == "alarm-owner-modal-close":
        ui_state["modal_open"] = False
        ui_state["modal_row_id"] = None
    elif isinstance(triggered, dict) and triggered.get("type") == "alarm-owner-link":
        row_id = triggered.get("index")
        if row_id in _alert_row_by_id():
            ui_state["selected_row_id"] = row_id
            ui_state["modal_row_id"] = row_id
            ui_state["modal_open"] = True

    if triggered == "alarm-history-tabs" or ui_state.get("selected_row_id") not in filtered_ids:
        ui_state["selected_row_id"] = _default_alert_row_id(tab_value)
        if ui_state.get("modal_row_id") not in filtered_ids:
            ui_state["modal_open"] = False
            ui_state["modal_row_id"] = None

    return ui_state


@callback(
    Output("alarm-history-table-shell", "children"),
    Input("alarm-history-tabs", "value"),
    Input("alarm-ui-state", "data"),
)
def update_alarm_history_table(tab_value, ui_state):
    filtered_rows = _filter_alert_rows(tab_value)
    selected_row_id = (ui_state or {}).get("selected_row_id")
    if selected_row_id not in {row["id"] for row in filtered_rows}:
        selected_row_id = _default_alert_row_id(tab_value)
    return _build_alarm_table(filtered_rows, selected_row_id)


@callback(
    Output("alarm-detail-shell", "children"),
    Input("alarm-ui-state", "data"),
)
def update_alarm_detail_shell(ui_state):
    selected_row_id = (ui_state or {}).get("selected_row_id")
    return _build_alert_detail_section(_alert_row_by_id().get(selected_row_id))


@callback(
    Output("alarm-owner-modal", "style"),
    Output("alarm-owner-modal-body", "children"),
    Input("alarm-ui-state", "data"),
    prevent_initial_call=True,
)
def toggle_owner_modal(ui_state):
    ui_state = ui_state or {}
    if not ui_state.get("modal_open"):
        return {"display": "none"}, _owner_modal_body(None)

    row = _alert_row_by_id().get(ui_state.get("modal_row_id"))
    if row is None:
        return {"display": "none"}, _owner_modal_body(None)

    return {"display": "block"}, _owner_modal_body(row)
