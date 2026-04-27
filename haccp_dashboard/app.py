import os, sys
# Ensure the repo root (parent of this file's directory) is on sys.path so that
# `from haccp_dashboard.xxx import ...` works when running `python haccp_dashboard/app.py`
_repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _repo_root not in sys.path:
    sys.path.insert(0, _repo_root)

# --- Dash 콜백 관련 import: 반드시 최상단에 위치해야 함 ---
from dash import callback, Input, Output, State, ctx, no_update
import dash
from dash import dcc, html
import dash_bootstrap_components as dbc

# --- AI 어시스턴트 채팅 내역 → 채팅창 표시 ---
@callback(
    Output("chat", "children"),
    Input("ai-chat-history", "data"),
)
def update_ai_chat(chat_history):
    from haccp_dashboard.lib.main_helpers import ai_chat_bubble
    if not chat_history:
        return []
    return [ai_chat_bubble(msg.get("role", "user"), msg.get("text", "")) for msg in chat_history]

app = dash.Dash(
    __name__,
    use_pages=True,
    suppress_callback_exceptions=True,
    external_stylesheets=[dbc.themes.BOOTSTRAP],
    external_scripts=["https://unpkg.com/three@0.160.0/build/three.min.js"],
)
server = app.server

from haccp_dashboard.pages.main_helpers import (
    DEFAULT_AI_HISTORY,
    DEFAULT_PANEL_STATE,
    build_ai_assistant_sidebar,
    build_ai_sidebar_style,
    build_ai_sidebar_content_style,
    build_alarm_panel_style,
    build_content_shell_style,
    build_dm_panel_style,
    build_report_panel_style,
    get_api_base_url,
    get_runtime_env_value,
)

_ENABLE_EMBEDDED_BRIDGE = str(get_runtime_env_value("HACCP_ENABLE_EMBEDDED_BRIDGE", "0")).strip().lower() in {"1", "true", "yes", "on"}
if _ENABLE_EMBEDDED_BRIDGE:
    from haccp_dashboard.api_routes import bp as external_api_bp  # noqa: E402

    server.register_blueprint(external_api_bp)

_STREAM_TOKEN = get_runtime_env_value("HACCP_STREAM_TOKEN", "")
_CONFIGURED_API_BASE_URL = get_runtime_env_value("HACCP_API_BASE_URL", get_runtime_env_value("API_BASE_URL", ""))
if _ENABLE_EMBEDDED_BRIDGE and not str(_CONFIGURED_API_BASE_URL or "").strip():
    _STREAM_URL = "/api/dashboard-stream"
else:
    _STREAM_URL = f"{get_api_base_url().rstrip('/')}/api/dashboard-stream"

# ── (선택) Socket.IO 설정: Flutter/외부 클라이언트 실시간 구독 ────────────────
socketio = None
try:
    from flask_socketio import SocketIO  # type: ignore

    socketio = SocketIO(
        server,
        cors_allowed_origins="*",
        async_mode=(get_runtime_env_value("HACCP_SOCKETIO_ASYNC_MODE", "threading") or "threading"),
    )
    server.extensions["socketio"] = socketio
except Exception:
    socketio = None

_HEADER_ICON_BUTTON_STYLE = {}  # legacy – replaced by className="header-btn"
_HEADER_PILL_BUTTON_STYLE = {}  # legacy – replaced by className="header-pill"


def _merge_styles(*styles):
    merged = {}
    for style in styles:
        merged.update(style)
    return merged


def _build_header_button(children, component_id, title, style):
    return html.Button(children, id=component_id, n_clicks=0, style=style, title=title)

# ── 상단 헤더 ────────────────────────────────────────────────────────────────
header = html.Div(
    [
        # 좌측: 브랜드 (비움)
        html.Div(),
        # 우측: 액션 버튼들
        html.Div(
            [
                # 시계
                html.Div("-- : -- : --", id="header-clock", className="header-clock"),
                # 알림 버튼
                html.Button(
                    [
                        html.Span("🔔", style={"fontSize": "15px", "lineHeight": "1"}),
                        html.Span("", id="alarm-badge", style={"display": "none"}),
                    ],
                    id="alarm-btn",
                    n_clicks=0,
                    className="header-btn",
                    title="알람",
                ),
                # 메시지 버튼
                html.Button(
                    html.Span("💬", style={"fontSize": "15px", "lineHeight": "1"}),
                    id="dm-btn",
                    n_clicks=0,
                    className="header-btn",
                    title="메시지",
                ),
                # 보고서 pill
                html.Button(
                    "보고서",
                    id="report-btn",
                    n_clicks=0,
                    className="header-pill",
                    title="현재 페이지 보고서",
                ),
                # AI pill
                html.Button(
                    "AI ⚙️",
                    id="ai-btn",
                    n_clicks=0,
                    className="header-pill header-ai-pill",
                    title="AI Assistant",
                ),
            ],
            style={"display": "flex", "alignItems": "center", "gap": "8px"},
        ),
    ],
    style={
        "height": "60px",
        "background": "white",
        "display": "flex",
        "alignItems": "center",
        "justifyContent": "space-between",
        "padding": "0 24px",
        "borderBottom": "1px solid #e5e7eb",
        "position": "fixed",
        "top": "0",
        "left": "var(--sidebar-width, 260px)",
        "right": "0",
        "zIndex": "999",
        "boxShadow": "0 1px 4px rgba(0,0,0,0.04)",
    },
)

# ── 좌측 사이드바 (다크 네이비) ──────────────────────────────────────────────
sidebar = html.Div(
    [
        # 브랜드 텍스트 영역 (아이콘 제거)
        html.Div(
            [
                html.Div(
                    [
                        html.Div("HACCP 관리", className="sidebar-brand-name"),
                        html.Div("우유 공정관리 모니터링", className="sidebar-brand-sub"),
                    ]
                ),
            ],
            className="sidebar-brand",
        ),
        # 메뉴 섹션
        html.Div("품질관리", className="sidebar-section-label"),
        dbc.NavLink(
            "QC/QA 대시보드",
            href="/",
            active="exact",
            className="sidebar-link",
        ),
        dbc.NavLink(
            "가열 살균 공정",
            href="/heating",
            active="exact",
            className="sidebar-link",
        ),
        dbc.NavLink(
            "최종 품질 검사",
            href="/final-inspection",
            active="exact",
            className="sidebar-link",
        ),
        dbc.NavLink(
            "알람 이력 관리",
            href="/alarm-history",
            active="exact",
            className="sidebar-link",
        ),
        # 하단 버전 정보
        html.Div("© 2026 매일유업 HACCP v2.0", className="sidebar-version"),
    ],
    className="sidebar",
)

content = html.Div(
    html.Div(
        dash.page_container,
        id="scaled-main-stage",
        className="scaled-main-stage",
    ),
    id="content-shell",
    className="content content-scaled-shell",
    style=build_content_shell_style(DEFAULT_PANEL_STATE["ai_collapsed"]),
)

report_panel = html.Div(
    id="report-panel",
    style=build_report_panel_style(DEFAULT_PANEL_STATE["report_open"]),
    children=[
        # 배경(backdrop) – 클릭 시 닫기
        html.Div(
            id="report-backdrop",
            n_clicks=0,
            style={
                "position": "absolute",
                "inset": "0",
                "cursor": "pointer",
                "zIndex": "0",
            },
        ),
        # 모달 카드
        html.Div(
            [
                # 헤더
                html.Div(
                    [
                        html.Div(
                            id="report-title",
                            children="페이지 요약 보고서",
                            style={"fontSize": "17px", "fontWeight": "800", "color": "#0f172a"},
                        ),
                        html.Button(
                            "✕",
                            id="report-close-btn",
                            n_clicks=0,
                            style={
                                "background": "none",
                                "border": "none",
                                "fontSize": "20px",
                                "cursor": "pointer",
                                "color": "#6b7280",
                                "lineHeight": "1",
                                "padding": "4px 8px",
                                "borderRadius": "6px",
                            },
                        ),
                    ],
                    style={
                        "display": "flex",
                        "justifyContent": "space-between",
                        "alignItems": "center",
                        "padding": "16px 20px 12px",
                        "borderBottom": "1px solid #e5e7eb",
                    },
                ),
                # 이미지 영역 (세로 스크롤)
                html.Div(
                    id="report-content",
                    style={
                        "overflowY": "auto",
                        "maxHeight": "calc(85vh - 68px)",
                        "padding": "20px",
                        "display": "flex",
                        "justifyContent": "center",
                    },
                ),
            ],
            style={
                "position": "relative",
                "zIndex": "1",
                "background": "white",
                "borderRadius": "16px",
                "boxShadow": "0 24px 60px rgba(15,23,42,0.2)",
                "width": "min(680px, calc(100vw - 48px))",
                "maxHeight": "85vh",
                "overflow": "hidden",
                "display": "flex",
                "flexDirection": "column",
                "transform": "translateY(0)",
                "transition": "transform 0.22s ease",
            },
        ),
    ],
)

alarm_panel = html.Div(
    id="alarm-panel",
    style=build_alarm_panel_style(DEFAULT_PANEL_STATE),
    children=[
        html.Div(
            "🔔 알람",
            style={
                "padding": "14px 16px",
                "fontWeight": "bold",
                "fontSize": "14px",
                "borderBottom": "1px solid #f0f0f0",
                "background": "#fafafa",
                "position": "sticky",
                "top": "0",
                "zIndex": "10",
            },
        ),
        html.Div(id="alarm-list", style={"padding": "8px"}),
    ],
)

dm_panel = html.Div(
    id="dm-panel",
    style=build_dm_panel_style(DEFAULT_PANEL_STATE),
    children=[
        html.Div(
            [
                html.Div("💬 메시지", style={"fontWeight": "bold", "fontSize": "14px"}),
                html.Div(id="dm-status-banner", style={"marginTop": "8px"}),
            ],
            style={"padding": "14px 16px", "borderBottom": "1px solid #f0f0f0", "background": "#fafafa"},
        ),
        html.Div(id="ccp-chat", style={"flex": "1", "padding": "12px", "overflowY": "auto", "backgroundColor": "#fefdf8"}),
        html.Div(
            [
                dcc.Input(
                    id="ccp-input",
                    placeholder="메시지...",
                    style={"flex": "1", "border": "1px solid #ddd", "borderRadius": "6px", "padding": "8px", "fontSize": "12px"},
                ),
                html.Button(
                    "전송",
                    id="ccp-send",
                    n_clicks=0,
                    style={
                        "marginLeft": "8px",
                        "background": "#3b82f6",
                        "color": "white",
                        "border": "none",
                        "padding": "8px 12px",
                        "borderRadius": "6px",
                        "cursor": "pointer",
                        "fontSize": "12px",
                        "fontWeight": "600",
                    },
                ),
            ],
            style={"display": "flex", "padding": "12px", "borderTop": "1px solid #f0f0f0", "gap": "8px"},
        ),
    ],
)


# === CALLBACKS: 상단 버튼 토글 및 AI 채팅 ===
from dash import Input, Output, State, ctx, callback, no_update
import dash
import json

app.layout = html.Div([
    dcc.Location(id="url"),
    dcc.Store(id="ai-chat-history", data=DEFAULT_AI_HISTORY),
    dcc.Store(id="panel-state", data=DEFAULT_PANEL_STATE),
    dcc.Store(id="sensor-cache", data=[]),
    dcc.Store(id="alert-cache", data=[]),
    dcc.Store(id="runtime-api-status", data={"text": "실시간 API 상태 확인 중입니다.", "level": "info"}),
    dcc.Store(id="dm-local-messages", data=[]),
    dcc.Store(id="dm-status", data={"text": "Slack 상태를 확인 중입니다.", "level": "info"}),
    dcc.Store(id="read-alerts", data=[]),
    dcc.Store(id="heating-selected-batch-store", data=None),  # 라인카드 → 가열살균공정 연동
    html.Button(id="runtime-sse-event", n_clicks=0, title="", style={"display": "none"}),
    html.Div(
        id="runtime-sse-config",
        **{
            "data-stream-url": _STREAM_URL,
            "data-stream-token": _STREAM_TOKEN,
        },
        style={"display": "none"},
    ),
    dcc.Interval(id="runtime-poll", interval=180000, n_intervals=0),
    dcc.Interval(id="chat-refresh", interval=180000),
    dcc.Interval(id="clock-interval", interval=1000, n_intervals=0),
    header,
    sidebar,
    content,
    build_ai_assistant_sidebar(),
    alarm_panel,
    dm_panel,
    report_panel,
])

# --- 상단 버튼 클릭 시 패널/사이드바 토글 ---
@callback(
    Output("panel-state", "data"),
    [
        Input("ai-btn", "n_clicks"),
        Input("alarm-btn", "n_clicks"),
        Input("dm-btn", "n_clicks"),
        Input("report-btn", "n_clicks"),
        Input("report-close-btn", "n_clicks"),
        Input("report-backdrop", "n_clicks"),
        Input("collapse-ai-btn", "n_clicks"),
    ],
    State("panel-state", "data"),
    prevent_initial_call=True,
)
def toggle_panels(ai_n, alarm_n, dm_n, report_n, report_close_n, backdrop_n, collapse_ai_n, panel_state):
    triggered = ctx.triggered_id
    if not panel_state:
        panel_state = DEFAULT_PANEL_STATE.copy()
    # 복사본 생성
    state = dict(panel_state)
    # 버튼별 토글/열기/닫기
    if triggered == "ai-btn":
        state["ai_collapsed"] = not state.get("ai_collapsed", True)
    elif triggered == "collapse-ai-btn":
        state["ai_collapsed"] = True
    elif triggered == "alarm-btn":
        state["alarm_open"] = not state.get("alarm_open", False)
        # 패널 중복 열림 방지: 메시지/보고서 닫기
        state["dm_open"] = False
        state["report_open"] = False
    elif triggered == "dm-btn":
        state["dm_open"] = not state.get("dm_open", False)
        state["alarm_open"] = False
        state["report_open"] = False
    elif triggered == "report-btn":
        state["report_open"] = not state.get("report_open", False)
        state["alarm_open"] = False
        state["dm_open"] = False
    elif triggered in ("report-close-btn", "report-backdrop"):
        state["report_open"] = False
    return state

# --- panel-state 변화에 따른 스타일 반영 (AI/알람/DM/보고서) ---
@callback(
    Output("ai-sidebar", "style"),
    Output("ai-sidebar-content", "style"),
    Output("content-shell", "style"),
    Output("alarm-panel", "style"),
    Output("dm-panel", "style"),
    Output("report-panel", "style"),
    Input("panel-state", "data"),
)
def apply_panel_styles(panel_state):
    if not panel_state:
        panel_state = DEFAULT_PANEL_STATE.copy()
    ai_collapsed = bool(panel_state.get("ai_collapsed", True))
    report_open = bool(panel_state.get("report_open", False))
    return (
        build_ai_sidebar_style(ai_collapsed),
        build_ai_sidebar_content_style(ai_collapsed),
        build_content_shell_style(ai_collapsed),
        build_alarm_panel_style(panel_state),
        build_dm_panel_style(panel_state),
        build_report_panel_style(report_open),
    )


# --- 헤더 시계 1초 갱신 ---
@callback(
    Output("header-clock", "children"),
    Input("clock-interval", "n_intervals"),
)
def update_header_clock(_n):
    from datetime import datetime
    now = datetime.now()
    ampm = "오전" if now.hour < 12 else "오후"
    hour12 = now.hour % 12
    if hour12 == 0:
        hour12 = 12
    return f"⏰ {ampm} {hour12:02d}:{now.minute:02d}:{now.second:02d}"


# --- SSE/폴링: sensor-cache / alert-cache 갱신 ---
@callback(
    Output("sensor-cache", "data"),
    Output("alert-cache", "data"),
    Output("runtime-api-status", "data"),
    Input("runtime-poll", "n_intervals"),
    Input("runtime-sse-event", "n_clicks"),
    State("runtime-sse-event", "title"),
    State("sensor-cache", "data"),
    State("alert-cache", "data"),
    State("runtime-api-status", "data"),
)
def ingest_runtime_event(_n_intervals, _n_clicks, raw_payload, sensor_cache, alert_cache, runtime_status):
    import hashlib
    from datetime import datetime
    triggered = ctx.triggered_id

    if triggered in (None, "runtime-poll"):
        from haccp_dashboard.lib.main_helpers import get_alert_data, get_runtime_api_status, get_sensor_data
        sensor_rows = get_sensor_data()
        alerts = get_alert_data(sensor_rows=sensor_rows)
        status = get_runtime_api_status()
        return sensor_rows, alerts, status

    if triggered != "runtime-sse-event" or not raw_payload:
        return no_update, no_update, no_update

    try:
        payload = json.loads(raw_payload)
    except Exception:
        return no_update, no_update, no_update

    sensor_cache = list(sensor_cache or [])
    alert_cache = list(alert_cache or [])
    runtime_status = dict(runtime_status or {})

    if isinstance(payload, dict):
        def _norm_sensors(items):
            out = []
            for item in (items or []):
                if not isinstance(item, dict):
                    continue
                t = item.get("temperature") or item.get("temperature_celsius") or item.get("T")
                ph = item.get("ph") or item.get("pH")
                out.append({**item, "temperature": t, "ph": ph})
            return out

        def _norm_alerts(items):
            out = []
            for item in (items or []):
                if not isinstance(item, dict):
                    continue
                level = item.get("level") or item.get("severity") or "정보"
                message = item.get("message") or item.get("text") or ""
                ts = item.get("time") or item.get("timestamp") or datetime.now().isoformat()
                aid = item.get("id") or hashlib.md5(f"{level}|{message}|{ts}".encode()).hexdigest()[:12]
                out.append({**item, "id": aid, "level": level, "message": message, "time": ts})
            return out

        if "sensor_rows" in payload and isinstance(payload["sensor_rows"], list):
            sensor_cache = _norm_sensors(payload["sensor_rows"])
        elif isinstance(payload.get("sensor"), dict) and isinstance(payload["sensor"].get("data"), list):
            sensor_cache = _norm_sensors(payload["sensor"]["data"])

        if "alerts" in payload and isinstance(payload["alerts"], list):
            alert_cache = _norm_alerts(payload["alerts"])
        elif isinstance(payload.get("alerts"), dict) and isinstance(payload["alerts"].get("alerts"), list):
            alert_cache = _norm_alerts(payload["alerts"]["alerts"])

        if "runtime_status" in payload and isinstance(payload["runtime_status"], dict):
            runtime_status.update(payload["runtime_status"])

    return sensor_cache, alert_cache, runtime_status


# --- Runtime API 배너 갱신 ---
@callback(
    Output("runtime-api-banner", "children"),
    Input("runtime-api-status", "data"),
)
def render_runtime_api_banner(status):
    status = dict(status or {})
    text = status.get("text") or "실시간 API 상태 확인 중입니다."
    level = status.get("level") or "info"
    from haccp_dashboard.lib.main_helpers import build_status_banner
    return build_status_banner(text, level)


# --- 알람 리스트 + 뱃지 (읽음 처리 포함) ---
@callback(
    Output("alarm-list", "children"),
    Output("alarm-badge", "children"),
    Output("alarm-badge", "style"),
    Output("read-alerts", "data"),
    Input("alert-cache", "data"),
    Input({"type": "alarm-item", "index": dash.ALL}, "n_clicks"),
    State("read-alerts", "data"),
)
def render_alarms(alerts, alarm_clicks, read_alerts):
    from haccp_dashboard.lib.main_helpers import alarm_item
    alerts = list(alerts or [])
    read_alerts = set(read_alerts or [])
    triggered = ctx.triggered_id
    if isinstance(triggered, dict) and triggered.get("type") == "alarm-item":
        aid = triggered.get("index")
        if aid is not None:
            read_alerts.add(aid)
    unread_count = 0
    items = []
    for alert in alerts[:30]:
        aid = alert.get("id")
        is_read = aid in read_alerts if aid is not None else False
        if not is_read:
            unread_count += 1
        try:
            items.append(alarm_item(alert, is_read=is_read, prefix="alarm-item"))
        except Exception:
            continue
    if not items:
        items = [html.Div("표시할 알람이 없습니다.", style={"color": "#64748b", "padding": "12px 10px", "fontSize": "13px"})]
    if unread_count <= 0:
        return items, "", {"display": "none"}, sorted(read_alerts)
    badge_style = {
        "display": "inline-flex", "alignItems": "center", "justifyContent": "center",
        "position": "absolute", "top": "2px", "right": "2px",
        "minWidth": "18px", "height": "18px", "padding": "0 5px",
        "borderRadius": "999px", "background": "#ef4444", "color": "white",
        "fontSize": "11px", "fontWeight": "800", "lineHeight": "1",
    }
    return items, str(unread_count), badge_style, sorted(read_alerts)


# --- 메시지 패널: Slack 연동 (없으면 로컬 미리보기) ---
@callback(
    Output("ccp-chat", "children"),
    Output("dm-local-messages", "data"),
    Output("ccp-input", "value"),
    Output("dm-status", "data"),
    Output("dm-status-banner", "children"),
    Input("chat-refresh", "n_intervals"),
    Input("ccp-send", "n_clicks"),
    State("ccp-input", "value"),
    State("dm-local-messages", "data"),
    prevent_initial_call=True,
)
def refresh_or_send_dm(_n_intervals, send_clicks, draft_text, local_messages):
    from datetime import datetime
    from haccp_dashboard.lib.main_helpers import build_status_banner, get_slack_messages, kakao_bubble, send_to_slack
    local_messages = list(local_messages or [])
    status_text = "Slack 상태를 확인 중입니다."
    status_level = "info"
    clear_input = no_update
    if ctx.triggered_id == "ccp-send":
        text = (draft_text or "").strip()
        if text:
            local_messages.append({"user": "Me", "text": text, "time": datetime.now().strftime("%H:%M"), "is_me": True})
            ok, message = send_to_slack(text)
            status_text = message
            status_level = "info" if ok else "warning"
            clear_input = ""
    messages, banner_text, banner_level = get_slack_messages(local_messages=local_messages)
    status_text = banner_text or status_text
    status_level = banner_level or status_level
    bubbles = []
    for msg in messages[-40:]:
        bubbles.append(kakao_bubble(
            msg.get("user") or "Slack",
            msg.get("text") or "",
            is_me=bool(msg.get("is_me")),
            time_label=msg.get("time") or "",
        ))
    status_data = {"text": status_text, "level": status_level}
    return bubbles, local_messages, clear_input, status_data, build_status_banner(status_text, status_level)


# --- 보고서 모달: URL 기반 요약 양식 이미지 ---
_REPORT_IMAGE_MAP = {
    "/":                "/assets/report_forms/report_main.png",
    "/heating":         "/assets/report_forms/report_heating.png",
    "/final-inspection":"/assets/report_forms/report_final_inspection.png",
    "/alarm-history":   "/assets/report_forms/report_alarm_history.png",
}
_REPORT_TITLE_MAP = {
    "/":                "메인페이지 요약 보고서",
    "/heating":         "가열살균공정 요약 보고서",
    "/final-inspection":"최종제품검사 요약 보고서",
    "/alarm-history":   "알람이력 관리 요약 보고서",
}

@callback(
    Output("report-content", "children"),
    Output("report-title", "children"),
    Input("panel-state", "data"),
    State("url", "pathname"),
)
def render_report(panel_state, pathname):
    panel_state = dict(panel_state or {})
    if not panel_state.get("report_open"):
        return no_update, no_update
    try:
        from haccp_dashboard.components.report_forms import build_report_for_path
        content, title = build_report_for_path(pathname)
    except Exception as exc:
        path = (pathname or "/").rstrip("/") or "/"
        img_src = _REPORT_IMAGE_MAP.get(path, _REPORT_IMAGE_MAP["/"])
        title = _REPORT_TITLE_MAP.get(path, "페이지 요약 보고서")
        content = html.Img(
            src=img_src,
            style={"maxWidth": "100%", "borderRadius": "6px", "display": "block"},
            alt=title,
        )
    return content, title


# --- ESC 키 → 보고서 모달 닫기 (clientside) ---
app.clientside_callback(
    """
    function(panelState) {
        function onKeyDown(e) {
            if (e.key === 'Escape') {
                var btn = document.getElementById('report-close-btn');
                if (btn) { btn.click(); }
            }
        }
        document.removeEventListener('keydown', onKeyDown);
        if (panelState && panelState.report_open) {
            document.addEventListener('keydown', onKeyDown);
        }
        return window.dash_clientside.no_update;
    }
    """,
    Output("report-close-btn", "title"),
    Input("panel-state", "data"),
)

# --- AI 어시스턴트 채팅 입력/전송 ---
@callback(
    Output("ai-chat-history", "data"),
    Output("input", "value"),
    Input("btn", "n_clicks"),
    State("input", "value"),
    State("ai-chat-history", "data"),
    State("sensor-cache", "data"),
    State("alert-cache", "data"),
    prevent_initial_call=True,
)
def send_ai_message(n_clicks, user_input, chat_history, sensor_cache, alert_cache):
    if not user_input or not n_clicks:
        return no_update, no_update
    if not chat_history:
        chat_history = []
    chat_history = list(chat_history)
    chat_history.append({"role": "user", "text": user_input})
    try:
        from haccp_dashboard.pages.main_helpers import ai_response
        ai_reply = ai_response(user_input, sensor_rows=sensor_cache, alerts=alert_cache)
        if isinstance(ai_reply, dict) and "text" in ai_reply:
            answer = ai_reply["text"]
        else:
            answer = str(ai_reply)
    except Exception as e:
        answer = f"[AI 응답 오류] {e}"
    chat_history.append({"role": "assistant", "text": answer})
    return chat_history, ""

if __name__ == "__main__":
    host = "127.0.0.1"
    port = 8050
    print(f"Dash server starting at http://{host}:{port}")
    enable_socketio = str(get_runtime_env_value("HACCP_ENABLE_SOCKETIO", "0")).strip().lower() in {"1", "true", "yes", "on"}
    if enable_socketio and socketio is not None:
        socketio.run(server, host=host, port=port, debug=True, allow_unsafe_werkzeug=True)
    else:
        app.run(host=host, port=port, debug=True, dev_tools_ui=False, dev_tools_props_check=False)
