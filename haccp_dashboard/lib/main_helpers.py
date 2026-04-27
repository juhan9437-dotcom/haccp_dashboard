import hashlib
import ipaddress
import os
import requests
import math
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from time import monotonic
from urllib.parse import urlparse

import numpy as np
import pandas as pd
from dash import html, dcc

from .process_spec import (
    DAILY_OPERATION_START_HOUR,
    LINE_COUNT,
    LOTS_PER_DAY_PER_LINE,
    OPERATION_DAYS,
    OPERATION_HOURS_PER_DAY,
    PROCESS_STAGE_LABELS as STATE_LABELS,
    PROCESS_STAGE_ORDER as STATE_ORDER,
    TIME_LOT_HOURS,
    TIME_LOT_MINUTES,
    TOTAL_BATCH_COUNT,
)

from .heating_risk import (
    HEATING_DANGER_Z_ABS,
    HEATING_WARNING_Z_ABS,
    classify_heating_sensor_row,
)

# --- Dashboard scenario (fixed operational time) ---
# 요구사항: 대시보드 전체의 "현재 시점"을 특정 로트(=배치) 진행 중인 시점으로 고정한다.
# - 여기서 "8번째 배치"는 일일 2시간 time-based lot 순번(로트 순번)을 의미한다.
# - 3개 라인이 병렬로 운영되므로, 현재 로트 순번은 3개 라인에 동시에 적용된다.
DASHBOARD_SCENARIO_CURRENT_LOT_INDEX = int(os.getenv("HACCP_SCENARIO_CURRENT_LOT_INDEX", "8") or 8)
# 현재 로트(2시간) 내에서 어느 시점인지(분). 가열/냉각 인접 구간이 되도록 기본값을 설정.
DASHBOARD_SCENARIO_WITHIN_LOT_MINUTES = float(os.getenv("HACCP_SCENARIO_WITHIN_LOT_MINUTES", "52") or 52.0)


@lru_cache(maxsize=1)
def get_dashboard_anchor_day() -> pd.Timestamp:
    """시나리오 시간축의 기준 날짜(로컬 실행 날짜를 사용하되 캐시로 고정)."""

    return pd.Timestamp.now().normalize()


def get_dashboard_current_lot_index() -> int:
    """현재 진행 중인 일일 로트(=배치) 순번(1~10)."""

    value = int(DASHBOARD_SCENARIO_CURRENT_LOT_INDEX)
    return max(1, min(int(LOTS_PER_DAY_PER_LINE), value))


def get_dashboard_now() -> pd.Timestamp:
    """대시보드 전체에서 공유하는 '현재 운영 시점' (시나리오 고정)."""

    lot_index = get_dashboard_current_lot_index()
    within_minutes = float(DASHBOARD_SCENARIO_WITHIN_LOT_MINUTES)
    within_minutes = max(0.0, min(float(TIME_LOT_MINUTES) - 0.1, within_minutes))

    # Day 1의 로트 기준으로 진행 중인 시점(현실적인 공장: 하루 20h, 04:00 시작)
    return (
        get_dashboard_anchor_day()
        + pd.Timedelta(hours=int(DAILY_OPERATION_START_HOUR))
        + pd.Timedelta(minutes=int((lot_index - 1) * int(TIME_LOT_MINUTES) + within_minutes))
        + pd.Timedelta(seconds=15)
    )

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
OPENAI_CHAT_MODEL = os.getenv("OPENAI_CHAT_MODEL", "gpt-4.1-mini").strip() or "gpt-4.1-mini"
_WORKSPACE_ENV_PATH = Path(__file__).resolve().parent.parent / ".env"


def _read_float_env(name, default):
    try:
        return float(str(os.getenv(name, default)).strip())
    except (TypeError, ValueError):
        return float(default)


OPENAI_TIMEOUT_SECONDS = _read_float_env("OPENAI_TIMEOUT_SECONDS", 10.0)

# Avoid importing OpenAI SDK at module import time (Dash startup performance).
OpenAI = None
AI_CLIENT = None

# Requests session that ignores environment proxy variables (for private/internal endpoints).
_NO_PROXY_SESSION = None


def _should_bypass_proxy(url: str) -> bool:
    try:
        hostname = urlparse(url).hostname
    except Exception:
        hostname = None

    if not hostname:
        return False

    if hostname in {"localhost", "127.0.0.1"}:
        return True

    try:
        address = ipaddress.ip_address(hostname)
        return bool(address.is_private or address.is_loopback)
    except ValueError:
        return False


def _http_get(url: str, headers: dict | None = None, timeout: float | int = 3):
    if _should_bypass_proxy(url):
        global _NO_PROXY_SESSION
        if _NO_PROXY_SESSION is None:
            session = requests.Session()
            session.trust_env = False
            _NO_PROXY_SESSION = session
        return _NO_PROXY_SESSION.get(url, headers=headers, timeout=timeout)

    return requests.get(url, headers=headers, timeout=timeout)


@lru_cache(maxsize=1)
def _read_workspace_env_values():
    values = {}
    if not _WORKSPACE_ENV_PATH.exists():
        return values

    for raw_line in _WORKSPACE_ENV_PATH.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def get_runtime_env_value(name, default=""):
    env_value = os.getenv(name)
    if env_value is not None and str(env_value).strip() != "":
        return str(env_value).strip()
    return str(_read_workspace_env_values().get(name, default)).strip()


def _read_timeout_env(name: str, default: float) -> float:
    raw = get_runtime_env_value(name, str(default))
    try:
        value = float(str(raw).strip())
        return value if value > 0 else float(default)
    except Exception:
        return float(default)


def get_api_timeouts() -> tuple[float, float]:
    """Return (connect_timeout, read_timeout) for external API calls."""
    connect_timeout = _read_timeout_env("HACCP_API_CONNECT_TIMEOUT_SECONDS", 3.0)
    read_timeout = _read_timeout_env("HACCP_API_READ_TIMEOUT_SECONDS", 3.0)
    return connect_timeout, read_timeout


def _describe_requests_error(exc: Exception, url: str) -> str:
    message = str(exc)
    hostname = ""
    port = ""
    try:
        parsed = urlparse(url)
        hostname = parsed.hostname or ""
        port = str(parsed.port or "")
    except Exception:
        pass

    lowered = message.lower()
    if "proxyerror" in lowered or "unable to connect to proxy" in lowered:
        return f"ProxyError: environment proxy blocks request (url={url})"
    if "connecttimeout" in lowered or ("connect timeout" in lowered) or ("timed out" in lowered and "connect" in lowered):
        target = f"{hostname}:{port}" if hostname and port else url
        return f"ConnectTimeout: cannot reach {target} (remote server down/firewall/network)"
    if "connection refused" in lowered:
        target = f"{hostname}:{port}" if hostname and port else url
        return f"ConnectionRefused: {target} is not listening (service down/port blocked)"
    if "401" in lowered or "unauthorized" in lowered:
        return "Unauthorized(401): check X-API-Key matches server"
    if "getaddrinfo failed" in lowered or "name or service not known" in lowered:
        return f"DNS error: invalid host (url={url})"

    return message[:220]


def get_openai_chat_model():
    return get_runtime_env_value("OPENAI_CHAT_MODEL", OPENAI_CHAT_MODEL) or "gpt-4.1-mini"


def get_openai_timeout_seconds():
    raw_value = get_runtime_env_value("OPENAI_TIMEOUT_SECONDS", str(OPENAI_TIMEOUT_SECONDS))
    try:
        return float(raw_value)
    except (TypeError, ValueError):
        return float(OPENAI_TIMEOUT_SECONDS)


def get_openai_client():
    global OpenAI, AI_CLIENT

    if AI_CLIENT is not None:
        return AI_CLIENT
    api_key = get_runtime_env_value("OPENAI_API_KEY", OPENAI_API_KEY)
    if not api_key:
        return None
    try:
        if OpenAI is None:
            from openai import OpenAI as _OpenAI  # type: ignore

            OpenAI = _OpenAI
        AI_CLIENT = OpenAI(api_key=api_key)
        return AI_CLIENT
    except Exception:
        return None

# Avoid importing Slack SDK at module import time (Dash startup performance).
SLACK_CLIENT = None
SlackApiError = Exception


def _ensure_slack_client():
    global SLACK_CLIENT, SlackApiError

    if SLACK_CLIENT is not None:
        return SLACK_CLIENT

    token = os.getenv("SLACK_BOT_TOKEN", os.getenv("SLACK_TOKEN", ""))
    if not token:
        return None

    try:
        from slack_sdk import WebClient  # type: ignore
        from slack_sdk.errors import SlackApiError as _SlackApiError  # type: ignore

        SlackApiError = _SlackApiError
        SLACK_CLIENT = WebClient(token=token)
        return SLACK_CLIENT
    except Exception:
        SLACK_CLIENT = None
        return None

# ── 우유 생산 공정(연속 공정) + 시간 기반 배치(time-based lot) 정의 ─────────────
# - 생산 라인은 총 3개 (Line 1~3)
# - 운영 기간은 총 5일
# - 하루 20시간 가동
# NOTE: time-based lot process spec (3 lines / 5 days / 20h / 2h-lot / 150 batches,
# single-pass stage order) is defined in `haccp_dashboard/lib/process_spec.py` and
# imported near the top of this module.

# 시각화/샘플링용 "체크포인트" (배치(2시간) 진행률을 10등분한 구간 인덱스)
CHECKPOINT_COUNT = 10
ANALYSIS_Z_COLUMNS = ["T_z", "pH_z", "Mu_z", "Tau_z"]
PROCESS_Z_SCORE_SOURCE_COLUMNS = ["T", "pH", "Mu", "Tau"]
INT_COLUMNS = ["ccp_hold_temp_ok", "ccp_hold_time_ok"]
SNAPSHOT_RATIOS = [0.35, 0.55, 0.75]
CONTAMINATION_LABELS = {"no": "정상", "chem": "화학", "bio": "미생물"}
# Updated source file: df_noisy.csv -> batch_150_contaminated_onlylabel_final_v4.csv
PROCESS_BATCH_CSV_FILENAME = "batch_150_contaminated_onlylabel_final_v4.csv"
# Common image dataset directory (used across pages that rely on image-based inspection/CNN inference).
IMAGE_DATASET_DIRNAME = "resize_640 x 360"

# API 및 Slack 설정
API_BASE_URL = os.getenv("HACCP_API_BASE_URL", os.getenv("API_BASE_URL", "http://127.0.0.1:5000"))
# Never hardcode API keys in source. Read from env only.
API_KEY = os.getenv("HACCP_API_KEY", os.getenv("API_KEY", ""))
SLACK_CHANNEL_ID = os.getenv("SLACK_CHANNEL_ID", "")
SLACK_USER_ID = os.getenv("SLACK_USER_ID", "")
RUNTIME_API_CACHE_TTL_SECONDS = 4.0

HEADER_HEIGHT = 60
SIDEBAR_WIDTH = 260
AI_EXPANDED_WIDTH = 340
AI_COLLAPSED_WIDTH = 0
ALARM_PANEL_WIDTH = 340
DM_PANEL_WIDTH = 360
PANEL_GAP = 16

DEFAULT_AI_HISTORY = [
    {
        "role": "assistant",
        "text": "안녕하세요! HACCP 공정 분석을 지원하는 AI 어시스턴트입니다.\n\n살균 온도 기준, 이탈 대응 절차, 법적 유의사항, 문서 작성 등 QAQC 관련 질문을 바로 도와드릴 수 있습니다.",
    }
]

DEFAULT_DM_MESSAGES = [
    {
        "user": "박주한 (QAQC_4기)",
        "text": "금일 QAQC 점검 지시드립니다. QA/QC 운영 현황 기준으로 CCP 이탈 공정 수, 출하영향 공정 수, 미조치 고위험 알람 수를 우선 확인하고, 이상 원인과 조치 필요 여부를 보고서 형태로 정리해 주세요.",
        "time": "오전 9:38",
        "is_me": False,
    },
    {
        "user": "박주한 (QAQC_4기)",
        "text": "특히 위험 알람은 출하 영향 여부와 즉시 조치 항목을 분리해서 적어주시고, API 연결이 지연되면 대시보드 집계 기준으로 선보고 후 실제 데이터 확인본을 추가 공유해 주세요.",
        "time": "오전 9:39",
        "is_me": False,
    },
]

DEFAULT_PANEL_STATE = {"alarm_open": False, "dm_open": False, "ai_collapsed": True, "report_open": False}

_sensor_cache = {"expires_at": 0.0, "data": []}
_alert_cache = {"expires_at": 0.0, "data": []}
_runtime_api_status = {
    "text": "실시간 API 상태 확인 중입니다.",
    "level": "info",
    "source": "unknown",
    "last_error": "",
    "sensor_ok": False,
    "alerts_ok": False,
    "sensor_error": "",
    "alerts_error": "",
}


def get_api_base_url():
    return get_runtime_env_value("HACCP_API_BASE_URL", get_runtime_env_value("API_BASE_URL", API_BASE_URL)) or API_BASE_URL


def get_haccp_api_key():
    # Prefer explicit HACCP_API_KEY, then API_KEY, then legacy EXTERNAL_API_KEY.
    return get_runtime_env_value(
        "HACCP_API_KEY",
        get_runtime_env_value("API_KEY", get_runtime_env_value("EXTERNAL_API_KEY", API_KEY)),
    ) or API_KEY


def _set_runtime_api_status(**updates):
    _runtime_api_status.update(updates)

    sensor_ok = bool(_runtime_api_status.get("sensor_ok"))
    alerts_ok = bool(_runtime_api_status.get("alerts_ok"))
    sensor_error = _runtime_api_status.get("sensor_error", "")
    alerts_error = _runtime_api_status.get("alerts_error", "")
    errors = [message for message in (sensor_error, alerts_error) if message]
    last_error = " | ".join(errors)

    if sensor_ok and alerts_ok:
        source = "remote"
    elif sensor_ok or alerts_ok:
        source = "partial"
    else:
        source = "cache" if (_sensor_cache["data"] or _alert_cache["data"]) else "fallback"

    if sensor_ok and alerts_ok:
        text = f"실시간 API 연결 정상: {get_api_base_url()}/api/sensor-data, /api/alerts"
        level = "success"
    elif sensor_ok and not alerts_ok:
        text = f"센서 API는 실시간 연결 정상이고 알람 API는 폴백 상태입니다. {alerts_error}".strip()
        level = "warning"
    elif not sensor_ok and alerts_ok:
        text = f"알람 API는 실시간 연결 정상이고 센서 API는 폴백 상태입니다. {sensor_error}".strip()
        level = "warning"
    elif source == "cache":
        text = f"실시간 API 연결 실패로 최근 캐시 데이터를 유지 중입니다. {last_error}".strip()
        level = "warning"
    elif source == "fallback":
        text = f"실시간 API 연결 실패로 로컬 폴백 데이터로 동작 중입니다. {last_error}".strip()
        level = "danger"
    else:
        text = _runtime_api_status.get("text", "실시간 API 상태 확인 중입니다.")
        level = _runtime_api_status.get("level", "info")

    _runtime_api_status["text"] = text
    _runtime_api_status["level"] = level
    _runtime_api_status["source"] = source
    _runtime_api_status["last_error"] = last_error


def get_runtime_api_status():
    return {
        **_runtime_api_status,
        "api_base_url": get_api_base_url(),
        "sensor_endpoint": f"{get_api_base_url()}/api/sensor-data",
        "alerts_endpoint": f"{get_api_base_url()}/api/alerts",
        "stream_endpoint": f"{get_api_base_url()}/api/dashboard-stream",
        "has_api_key": bool(get_haccp_api_key()),
    }


def build_ai_sidebar_style(is_collapsed):
    width = AI_COLLAPSED_WIDTH if is_collapsed else AI_EXPANDED_WIDTH
    return {
        "width": f"{width}px",
        "position": "fixed",
        "right": "0",
        "top": f"{HEADER_HEIGHT}px",
        "height": f"calc(100vh - {HEADER_HEIGHT}px)",
        "background": "white",
        "borderLeft": "1px solid #e5e7eb",
        "display": "flex",
        "flexDirection": "column",
        "zIndex": "1000",
        "transition": "width 0.28s ease",
        "overflow": "hidden",
        "boxShadow": "-8px 0 20px rgba(15, 23, 42, 0.04)",
    }


def build_ai_sidebar_content_style(is_collapsed):
    return {
        "display": "none" if is_collapsed else "flex",
        "flexDirection": "column",
        "height": "100%",
        "opacity": "0" if is_collapsed else "1",
        "transition": "opacity 0.2s ease",
    }


def build_content_shell_style(is_ai_collapsed):
    reserved_width = 0 if is_ai_collapsed else AI_EXPANDED_WIDTH + PANEL_GAP
    width = f"calc(100vw - var(--sidebar-width, {SIDEBAR_WIDTH}px) - {reserved_width}px)"
    return {
        "marginTop": f"{HEADER_HEIGHT}px",
        "marginRight": f"{reserved_width}px",
        "height": f"calc(100vh - {HEADER_HEIGHT}px)",
        "width": width,
        "maxWidth": width,
        "minWidth": "0",
        "overflowX": "hidden",
        "overflowY": "auto",
        "transition": "margin-right 0.22s ease, width 0.22s ease, max-width 0.22s ease",
    }


def build_panel_base_style(is_open, right_offset, width, height):
    return {
        "position": "fixed",
        "top": f"{HEADER_HEIGHT + 14}px",
        "right": f"{right_offset}px",
        "width": f"{width}px",
        "height": height,
        "opacity": "1" if is_open else "0",
        "visibility": "visible" if is_open else "hidden",
        "pointerEvents": "auto" if is_open else "none",
        "transform": "translateY(0) scale(1)" if is_open else "translateY(-8px) scale(0.98)",
        "transition": "opacity 0.22s ease, transform 0.22s ease, right 0.28s ease",
        "display": "flex",
        "flexDirection": "column",
        "zIndex": "9999",
        "border": "1px solid #e5e7eb",
        "borderRadius": "16px",
        "boxShadow": "0 20px 40px rgba(0,0,0,0.12)",
    }


def build_alarm_panel_style(panel_state):
    ai_width = AI_COLLAPSED_WIDTH if panel_state.get("ai_collapsed") else AI_EXPANDED_WIDTH
    return {
        **build_panel_base_style(panel_state.get("alarm_open", False), ai_width + PANEL_GAP, ALARM_PANEL_WIDTH, "430px"),
        "background": "white",
        "overflowY": "auto",
    }


def build_dm_panel_style(panel_state):
    ai_width = AI_COLLAPSED_WIDTH if panel_state.get("ai_collapsed") else AI_EXPANDED_WIDTH
    right_offset = ai_width + PANEL_GAP if not panel_state.get("alarm_open") else ai_width + ALARM_PANEL_WIDTH + (PANEL_GAP * 2)
    return {
        **build_panel_base_style(panel_state.get("dm_open", False), right_offset, DM_PANEL_WIDTH, "500px"),
        "background": "#fefdf8",
    }


def build_report_panel_style(is_open):
    return {
        "position": "fixed",
        "inset": "0",
        "display": "flex",
        "alignItems": "center",
        "justifyContent": "center",
        "backgroundColor": "rgba(15,23,42,0.52)",
        "zIndex": "1400",
        "opacity": "1" if is_open else "0",
        "visibility": "visible" if is_open else "hidden",
        "pointerEvents": "auto" if is_open else "none",
        "transition": "opacity 0.2s ease, visibility 0.2s ease",
    }


def _clone_runtime_items(items):
    return [dict(item) if isinstance(item, dict) else item for item in (items or [])]


def normalize_contamination_value(value):
    normalized = str(value).strip().lower()
    if normalized in {"chem", "chemical"}:
        return "chem"
    if normalized in {"bio", "biological"}:
        return "bio"
    return "no"


def resolve_process_csv_path(base_dir: str | None = None) -> str:
    # Keep this stable regardless of the caller's module directory.
    project_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    return os.path.abspath(os.path.join(project_dir, PROCESS_BATCH_CSV_FILENAME))


def resolve_image_dataset_dir(base_dir: str | None = None) -> str:
    # Keep this stable regardless of the caller's module directory.
    project_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    return os.path.abspath(os.path.join(project_dir, IMAGE_DATASET_DIRNAME))


def _build_process_datetime(frame: pd.DataFrame) -> pd.DataFrame:
    if "datetime" in frame.columns:
        frame["datetime"] = pd.to_datetime(frame["datetime"], errors="coerce")
        if "timestamp" not in frame.columns:
            origin = frame["datetime"].min()
            frame["timestamp"] = (frame["datetime"] - origin).dt.total_seconds()
        return frame

    if "timestamp" not in frame.columns:
        raise KeyError("Process CSV must contain either 'datetime' or 'timestamp'.")

    frame["timestamp"] = pd.to_numeric(frame["timestamp"], errors="coerce")
    latest_timestamp = frame["timestamp"].max()
    latest_datetime = pd.Timestamp.now().floor("min")
    frame["datetime"] = latest_datetime - pd.to_timedelta(latest_timestamp - frame["timestamp"], unit="s")
    return frame


def _ensure_process_z_columns(frame: pd.DataFrame) -> pd.DataFrame:
    # Operational note:
    # Z-scores are used as "공정 안정도/이상징후" indicators (SPC-style) and should reflect
    # within-batch deviation rather than global dataset skew. Computing z-scores per-batch
    # keeps most runs in 정상 범위, while still surfacing genuinely unstable batches.
    batch_group = None
    if "batch_id" in frame.columns:
        try:
            batch_group = pd.to_numeric(frame["batch_id"], errors="coerce")
        except Exception:
            batch_group = frame["batch_id"]

    for source_column, z_column in zip(PROCESS_Z_SCORE_SOURCE_COLUMNS, ANALYSIS_Z_COLUMNS):
        if z_column in frame.columns:
            frame[z_column] = pd.to_numeric(frame[z_column], errors="coerce").fillna(0.0)
            continue

        if source_column not in frame.columns:
            frame[z_column] = 0.0
            continue

        source_series = pd.to_numeric(frame[source_column], errors="coerce")

        if batch_group is not None:
            mean_series = source_series.groupby(batch_group).transform("mean")
            std_series = source_series.groupby(batch_group).transform(lambda s: s.std(skipna=True, ddof=0))
            std_series = std_series.replace(0, np.nan)
            frame[z_column] = ((source_series - mean_series) / std_series).fillna(0.0)
        else:
            source_std = source_series.std(skipna=True, ddof=0)
            if pd.isna(source_std) or source_std == 0:
                frame[z_column] = 0.0
            else:
                frame[z_column] = ((source_series - source_series.mean(skipna=True)) / source_std).fillna(0.0)

    return frame


def _normalize_process_batch_frame(frame: pd.DataFrame) -> pd.DataFrame:
    # Normalize the new batch dataset schema so existing dashboard code can keep using datetime and z-score fields.
    frame = frame.copy()
    frame = _build_process_datetime(frame)
    frame["date"] = frame["datetime"].dt.date

    if "contamination" in frame.columns:
        frame["contamination"] = frame["contamination"].map(normalize_contamination_value)
    else:
        frame["contamination"] = "no"

    if "batch_id" in frame.columns:
        batch_start = frame.groupby("batch_id")["datetime"].transform("min")
        if "aligned_time" not in frame.columns:
            frame["aligned_time"] = (frame["datetime"] - batch_start).dt.total_seconds() / 60.0
    elif "aligned_time" not in frame.columns:
        frame["aligned_time"] = 0.0

    numeric_columns = [
        "timestamp",
        "aligned_time",
        "T",
        "pH",
        "Kappa",
        "Mu",
        "Tau",
        "Q_in",
        "Q_out",
        "P",
        "dTdt",
    ]
    for column in numeric_columns:
        if column in frame.columns:
            frame[column] = pd.to_numeric(frame[column], errors="coerce")

    for column in INT_COLUMNS:
        if column in frame.columns:
            frame[column] = pd.to_numeric(frame[column], errors="coerce").fillna(0).astype(int)
        else:
            frame[column] = 0

    frame = _ensure_process_z_columns(frame)

    checkpoint_count = int(CHECKPOINT_COUNT) if int(CHECKPOINT_COUNT) > 0 else 10
    if "batch_id" in frame.columns and "aligned_time" in frame.columns:
        max_aligned = frame.groupby("batch_id")["aligned_time"].transform("max").replace(0, np.nan)
        progress = (pd.to_numeric(frame["aligned_time"], errors="coerce") / max_aligned).fillna(0.0).clip(0.0, 1.0)
    elif "batch_id" in frame.columns and "datetime" in frame.columns:
        batch_start = frame.groupby("batch_id")["datetime"].transform("min")
        batch_end = frame.groupby("batch_id")["datetime"].transform("max")
        denom = (batch_end - batch_start).dt.total_seconds().replace(0, np.nan)
        progress = ((frame["datetime"] - batch_start).dt.total_seconds() / denom).fillna(0.0).clip(0.0, 1.0)
    else:
        progress = pd.Series(0.0, index=frame.index)

    frame["checkpoint_progress"] = progress.astype(float)
    raw_checkpoint = (frame["checkpoint_progress"] * checkpoint_count).astype(int) + 1
    frame["checkpoint"] = raw_checkpoint.clip(lower=1, upper=checkpoint_count).astype(int)

    # 시간 기반 배치(time-based lot) 일정 재구성:
    # - 3개 라인 × (2시간 로트 10개/일/라인) × 5일 = 총 150배치
    # - CSV의 원본 timestamp가 무엇이든, 배치별 aligned_time(분)을 2시간 범위로 정규화하고
    #   (일자/라인/일일 로트 순번) 스케줄을 고정으로 부여한다.
    if "batch_id" in frame.columns and "aligned_time" in frame.columns:
        batch_ids = (
            pd.to_numeric(frame["batch_id"], errors="coerce")
            .dropna()
            .astype(int)
            .unique()
            .tolist()
        )
        batch_ids.sort()
        if batch_ids:
            # 시나리오 고정 시간축: 운영 Day 1을 anchor_day로 두고 5일을 미래로 펼친다.
            # (대시보드 표시/요약은 별도 cutoff로 "현재 시점"까지만 보여준다.)
            base_day = get_dashboard_anchor_day()
            batch_start_map = {}
            batch_line_map = {}
            batch_run_map = {}
            batch_day_map = {}
            for idx, batch_id in enumerate(batch_ids):
                day_index = idx // (LINE_COUNT * LOTS_PER_DAY_PER_LINE)
                in_day_index = idx % (LINE_COUNT * LOTS_PER_DAY_PER_LINE)
                lot_index = in_day_index // LINE_COUNT
                line_index = in_day_index % LINE_COUNT
                line_id = line_index + 1
                day_start = (
                    base_day
                    + pd.Timedelta(days=int(day_index))
                    + pd.Timedelta(hours=int(DAILY_OPERATION_START_HOUR))
                )
                batch_start_map[int(batch_id)] = (
                    day_start
                    + pd.Timedelta(minutes=int(lot_index) * int(TIME_LOT_MINUTES))
                    + pd.Timedelta(seconds=line_index)
                )
                batch_line_map[int(batch_id)] = line_id
                # line_run은 "일일 로트 순번(2시간 구간)"을 의미한다. (1~10)
                batch_run_map[int(batch_id)] = int(lot_index) + 1
                batch_day_map[int(batch_id)] = day_index + 1

            batch_id_series = pd.to_numeric(frame["batch_id"], errors="coerce").astype("Int64")
            batch_start_series = batch_id_series.map(batch_start_map)
            frame["line_id"] = batch_id_series.map(batch_line_map).astype("Int64")
            frame["line_run"] = batch_id_series.map(batch_run_map).astype("Int64")
            frame["line_day"] = batch_id_series.map(batch_day_map).astype("Int64")

            aligned_time = pd.to_numeric(frame["aligned_time"], errors="coerce").fillna(0.0)
            max_per_batch = frame.groupby("batch_id")["aligned_time"].transform("max").replace(0, np.nan)
            scale = (float(TIME_LOT_MINUTES) / max_per_batch).replace([np.inf, -np.inf], np.nan).fillna(0.0)
            aligned_scaled = (aligned_time * scale).clip(lower=0.0, upper=float(TIME_LOT_MINUTES))
            frame["aligned_time"] = aligned_scaled.astype(float)
            frame["datetime"] = batch_start_series + pd.to_timedelta(frame["aligned_time"], unit="m")
            frame["date"] = frame["datetime"].dt.date
            origin = frame["datetime"].min()
            frame["timestamp"] = (frame["datetime"] - origin).dt.total_seconds()

            # 공정 단계는 배치(2시간) 진행률을 기준으로 10단계로 단 1회 순차 통과하도록 부여한다.
            p = frame["checkpoint_progress"].astype(float).fillna(0.0).clip(0.0, 1.0)
            frame["state"] = np.select(
                [
                    p < 0.06,
                    p < 0.14,
                    p < 0.22,
                    p < 0.30,
                    p < 0.48,
                    p < 0.62,
                    p < 0.74,
                    p < 0.86,
                    p < 0.94,
                ],
                [
                    "Receiving",
                    "Storage",
                    "Filter",
                    "Standardize",
                    "Heat",
                    "Hold",
                    "Cool",
                    "Fill",
                    "Inspect",
                ],
                default="Release",
            )

    # ── Derive CCP flags from process stage + temperature/hold duration ─────────
    # The raw dataset's ccp_* flags can be incomplete during in-progress stages.
    # For operational realism, compute CCP attainment based on the Hold stage.
    try:
        from haccp_dashboard.lib.process_spec import (
            CCP_APPLICABLE_STAGES,
            CCP_HOLD_MIN_SECONDS,
            CCP_HOLD_TEMP_RANGE_C,
        )

        if "batch_id" in frame.columns and "state" in frame.columns and "datetime" in frame.columns and "T" in frame.columns:
            batch_ids = pd.to_numeric(frame["batch_id"], errors="coerce").astype("Int64")
            state_series = frame["state"].astype(str)
            temp_series = pd.to_numeric(frame["T"], errors="coerce")

            hold_mask = state_series.eq("Hold") & batch_ids.notna()
            after_hold_mask = state_series.isin(CCP_APPLICABLE_STAGES) & batch_ids.notna()

            # Hold time attainment (per batch).
            if hold_mask.any():
                hold_start = frame.loc[hold_mask].groupby(batch_ids[hold_mask])["datetime"].transform("min")
                hold_elapsed = (frame.loc[hold_mask, "datetime"] - hold_start).dt.total_seconds()
                hold_time_ok_row = hold_elapsed.ge(float(CCP_HOLD_MIN_SECONDS))
                hold_time_ok_batch = hold_time_ok_row.groupby(batch_ids[hold_mask]).transform("max")
            else:
                hold_time_ok_row = pd.Series(False, index=frame.index)
                hold_time_ok_batch = pd.Series(False, index=frame.index)

            # Hold temperature attainment (per batch).
            low_temp, high_temp = float(CCP_HOLD_TEMP_RANGE_C[0]), float(CCP_HOLD_TEMP_RANGE_C[1])
            temp_ok_row = temp_series.ge(low_temp) & temp_series.le(high_temp)
            if hold_mask.any():
                hold_temp_ok_batch = temp_ok_row[hold_mask].groupby(batch_ids[hold_mask]).transform("min").astype(bool)
            else:
                hold_temp_ok_batch = pd.Series(False, index=frame.index)

            # Compose row-level flags:
            # - Pre-Hold stages: mark as OK (not applicable yet) to avoid false "CCP deviation" alarms.
            # - Hold stage: flags reflect "attained so far".
            # - Post-Hold stages: flags reflect final batch attainment.
            frame["ccp_hold_time_ok"] = 1
            frame.loc[hold_mask, "ccp_hold_time_ok"] = hold_time_ok_row.astype(int)
            if hold_mask.any():
                # Map batch-level to post-hold rows
                hold_time_ok_batch_map = hold_time_ok_row.groupby(batch_ids[hold_mask]).max()
                frame.loc[after_hold_mask, "ccp_hold_time_ok"] = batch_ids[after_hold_mask].map(hold_time_ok_batch_map).fillna(False).astype(int)

            frame["ccp_hold_temp_ok"] = 1
            frame.loc[hold_mask, "ccp_hold_temp_ok"] = temp_ok_row[hold_mask].fillna(False).astype(int)
            if hold_mask.any():
                hold_temp_ok_batch_map = temp_ok_row[hold_mask].groupby(batch_ids[hold_mask]).min()
                frame.loc[after_hold_mask, "ccp_hold_temp_ok"] = batch_ids[after_hold_mask].map(hold_temp_ok_batch_map).fillna(False).astype(int)
    except Exception:
        pass

    return frame.sort_values(["batch_id", "datetime"]).reset_index(drop=True)


@lru_cache(maxsize=4)
def _load_process_batch_dataframe_cached(csv_path: str) -> pd.DataFrame:
    frame = pd.read_csv(csv_path, encoding="utf-8-sig")
    return _normalize_process_batch_frame(frame)


def load_process_batch_dataframe(csv_path: str) -> pd.DataFrame:
    # Returning a full `.copy()` here was a major performance hit because many callbacks
    # repeatedly duplicated the entire dataframe in memory.
    # Treat the cached dataframe as read-only; callers that need mutation should copy explicitly.
    return _load_process_batch_dataframe_cached(csv_path)


def load_heating_dataset(base_dir: str) -> pd.DataFrame:
    csv_path = resolve_process_csv_path(base_dir)
    return load_process_batch_dataframe(csv_path)

# --- current process snapshot helpers (shared across pages) ---

def resolve_current_process_snapshot(
    process_frame: pd.DataFrame | None = None,
    *,
    now: pd.Timestamp | datetime | None = None,
) -> dict[int, dict]:
    """공통 '현재 시점 기준' 라인/배치 상태 스냅샷을 계산한다.

    메인/가열 페이지가 서로 다른 임시 로직으로 배치를 계산하지 않도록,
    동일 기준(현재 시각 + 공정 CSV 시간축)에 따라 산출한다.
    """

    frame = process_frame if process_frame is not None else load_process_batch_dataframe(resolve_process_csv_path(None))
    if frame is None or frame.empty:
        return {}

    # 기본값은 "대시보드 시나리오 현재 시점"을 사용한다.
    now_ts = get_dashboard_now() if now is None else pd.Timestamp(now)
    snapshot: dict[int, dict] = {}

    def _safe_float(value) -> float:
        try:
            return float(value)
        except Exception:
            return 0.0

    def _safe_int(value, default: int = 0) -> int:
        try:
            return int(value)
        except Exception:
            return int(default)

    for line_id in range(1, int(LINE_COUNT) + 1):
        try:
            line_view = frame[frame["line_id"].astype(int) == int(line_id)]
        except Exception:
            if "line_id" in frame.columns:
                line_view = frame[frame["line_id"] == line_id]
            else:
                line_view = frame

        if line_view is None or line_view.empty:
            continue

        line_view = line_view.sort_values("datetime")
        eligible = line_view[line_view["datetime"] <= now_ts]
        row = eligible.iloc[-1] if not eligible.empty else line_view.iloc[0]

        dt_value = row.get("datetime")
        try:
            dt_ts = pd.Timestamp(dt_value) if dt_value is not None else now_ts
        except Exception:
            dt_ts = now_ts

        stage_key = str(row.get("state") or "").strip()
        try:
            batch_id_value = int(row.get("batch_id")) if pd.notna(row.get("batch_id")) else None
        except Exception:
            batch_id_value = None

        snapshot[int(line_id)] = {
            "line_id": int(line_id),
            "batch_id": batch_id_value,
            "datetime": dt_ts.isoformat(),
            "state": stage_key,
            "stage_label": str(STATE_LABELS.get(stage_key, stage_key)) if stage_key else "",
            "line_run": _safe_int(row.get("line_run")) if "line_run" in line_view.columns else None,
            "line_day": _safe_int(row.get("line_day")) if "line_day" in line_view.columns else None,
            "T": _safe_float(row.get("T")),
            "pH": _safe_float(row.get("pH")),
            "T_z": _safe_float(row.get("T_z")),
            "pH_z": _safe_float(row.get("pH_z")),
            "Mu_z": _safe_float(row.get("Mu_z")),
            "Tau_z": _safe_float(row.get("Tau_z")),
            "ccp_hold_time_ok": _safe_int(row.get("ccp_hold_time_ok", 1), default=1),
            "ccp_hold_temp_ok": _safe_int(row.get("ccp_hold_temp_ok", 1), default=1),
        }

    return snapshot


def build_local_sensor_rows(now: pd.Timestamp | datetime | None = None) -> list[dict]:
    """실시간 API 불가 시 공정 CSV 기반으로 센서 행을 생성한다.

    classify_heating_sensor_row()에 필요한 z-score/CCP 플래그를 포함한다.
    """

    snapshot = resolve_current_process_snapshot(now=now)
    rows: list[dict] = []
    for line_id in range(1, int(LINE_COUNT) + 1):
        item = snapshot.get(int(line_id))
        if not isinstance(item, dict):
            continue
        rows.append(
            {
                "idx": int(line_id),
                "line_id": int(line_id),
                "batch_id": item.get("batch_id"),
                "timestamp": item.get("datetime"),
                "state": item.get("state"),
                "temperature": item.get("T"),
                "ph": item.get("pH"),
                "T": item.get("T"),
                "pH": item.get("pH"),
                "T_z": item.get("T_z"),
                "pH_z": item.get("pH_z"),
                "Mu_z": item.get("Mu_z"),
                "Tau_z": item.get("Tau_z"),
                "ccp_hold_time_ok": item.get("ccp_hold_time_ok", 1),
                "ccp_hold_temp_ok": item.get("ccp_hold_temp_ok", 1),
                "line_run": item.get("line_run"),
                "line_day": item.get("line_day"),
            }
        )
    return rows


def _sensor_label_ko(label: str) -> str:
    normalized = str(label or "").strip().lower()
    if normalized == "bio":
        return "미생물 오염 의심"
    if normalized == "chem":
        return "화학 오염 의심"
    if normalized == "no":
        return "정상"
    return normalized or "—"


@lru_cache(maxsize=256)
def predict_sensor_contamination_for_batch(batch_id: int) -> dict | None:
    """
    Batch 단위 센서 딥러닝(Track1/Track2) 오염 분류 결과를 반환합니다.

    - 입력: 공통 센서 CSV의 해당 batch 구간(row series)
    - 출력: models/inference.py의 `predict_contamination()` 결과 dict + `label_ko`
    - 캐시: 배치별 1회 계산 (대시보드 실시간 표시에서 중복 호출 방지)
    """
    try:
        batch_int = int(batch_id)
    except Exception:
        return None
    if batch_int <= 0:
        return None

    try:
        from haccp_dashboard.models import get_inference_status, predict_contamination
    except Exception:
        return None

    status = get_inference_status(attempt_load=False)
    if not bool(status.get("assets_present")):
        return None

    try:
        frame = load_process_batch_dataframe(resolve_process_csv_path())
    except Exception:
        return None

    if frame is None or frame.empty or "batch_id" not in frame.columns:
        return None

    try:
        batch_col = pd.to_numeric(frame["batch_id"], errors="coerce").fillna(-1).astype(int)
    except Exception:
        return None

    batch_frame = frame.loc[batch_col == batch_int]
    if batch_frame.empty:
        return None

    try:
        result = predict_contamination(batch_frame)
    except Exception:
        return None

    if isinstance(result, dict):
        result = dict(result)
        result["label_ko"] = _sensor_label_ko(result.get("label"))
        return result
    return None


def get_today_data(frame: pd.DataFrame) -> pd.DataFrame:
    # "오늘"은 실제 캘린더가 아니라 대시보드 운영 시나리오 기준의 운영일을 의미한다.
    now = get_dashboard_now()
    day = now.date()
    if "datetime" in frame.columns:
        view = frame[frame["datetime"] <= now]
    else:
        view = frame
    return view[view["date"] == day].copy()


def build_danger_warning_masks(frame: pd.DataFrame):
    danger_mask = pd.Series(False, index=frame.index)
    warning_mask = pd.Series(False, index=frame.index)

    if "ccp_hold_time_ok" in frame.columns:
        danger_mask |= frame["ccp_hold_time_ok"].eq(0)
    if "ccp_hold_temp_ok" in frame.columns:
        danger_mask |= frame["ccp_hold_temp_ok"].eq(0)

    for column in ANALYSIS_Z_COLUMNS:
        if column in frame.columns:
            z_abs = frame[column].abs()
            danger_mask |= z_abs.ge(HEATING_DANGER_Z_ABS)
            warning_mask |= z_abs.ge(HEATING_WARNING_Z_ABS) & z_abs.lt(HEATING_DANGER_Z_ABS)

    warning_mask &= ~danger_mask
    return danger_mask, warning_mask


def count_rows_by_threshold(frame: pd.DataFrame):
    if frame.empty:
        return 0, 0, 0

    danger_mask, warning_mask = build_danger_warning_masks(frame)
    normal_mask = ~(danger_mask | warning_mask)
    return int(normal_mask.sum()), int(warning_mask.sum()), int(danger_mask.sum())


def build_kpi_items(today_data: pd.DataFrame):
    daily_production = float(today_data["Q_out"].sum()) if "Q_out" in today_data.columns else 0.0

    process_key = "batch_id" if "batch_id" in today_data.columns else None

    ccp_deviation_mask = pd.Series(False, index=today_data.index)
    if "ccp_hold_time_ok" in today_data.columns:
        ccp_deviation_mask |= today_data["ccp_hold_time_ok"].eq(0)
    if "ccp_hold_temp_ok" in today_data.columns:
        ccp_deviation_mask |= today_data["ccp_hold_temp_ok"].eq(0)

    shipment_impact_mask = pd.Series(False, index=today_data.index)
    if "contamination" in today_data.columns:
        shipment_impact_mask |= today_data["contamination"].ne("no")
    if "ccp_hold_temp_ok" in today_data.columns:
        shipment_impact_mask |= today_data["ccp_hold_temp_ok"].eq(0)
    if "ccp_hold_time_ok" in today_data.columns:
        shipment_impact_mask |= today_data["ccp_hold_time_ok"].eq(0)

    if today_data.empty:
        ccp_process_count = 0
        shipment_impact_count = 0
        unresolved_high_risk_count = 0
    else:
        high_risk_alarm_mask, _warning_mask = build_danger_warning_masks(today_data)
        shipment_impact_mask |= high_risk_alarm_mask
        if process_key:
            ccp_process_count = int(today_data.loc[ccp_deviation_mask, process_key].nunique())
            shipment_impact_count = int(today_data.loc[shipment_impact_mask, process_key].nunique())
            unresolved_high_risk_count = int(today_data.loc[high_risk_alarm_mask, process_key].nunique())
        else:
            ccp_process_count = int(ccp_deviation_mask.sum())
            shipment_impact_count = int(shipment_impact_mask.sum())
            unresolved_high_risk_count = int(high_risk_alarm_mask.sum())

    return [
        {
            "title": "일일 총 생산량",
            "value": f"{daily_production:,.0f} L",
            "description": "당일 생산 완료 집계를 총 생산량입니다.",
            "icon": "mdi:milk",
            "accent": "#3498db",
        },
        {
            "title": "CCP 이탈 건수",
            "value": f"{ccp_process_count:,}",
            "description": "CCP 기준을 벗어난 공정 수입니다.",
            "icon": "mdi:alert-circle-outline",
            "accent": "#e74c3c",
        },
        {
            "title": "출하영향 공정 수",
            "value": f"{shipment_impact_count:,}",
            "description": "출하 보류 또는 추가 판정이 필요한 공정 수입니다.",
            "icon": "mdi:package-variant-closed",
            "accent": "#f39c12",
        },
        {
            "title": "미조치 고위험 알람 수",
            "value": f"{unresolved_high_risk_count:,}",
            "description": "즉시 조치가 필요한 고위험 알람 수입니다.",
            "icon": "mdi:alarm-light-outline",
            "accent": "#c0392b",
        },
    ]


def now_label():
    return datetime.now().strftime("%H:%M")


def _alert_id(*parts):
    return hashlib.md5("|".join(str(part) for part in parts).encode("utf-8")).hexdigest()[:12]


def _parse_time_label(value):
    if not value:
        return now_label()
    text = str(value)
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%H:%M:%S", "%H:%M"):
        try:
            return datetime.strptime(text[:19], fmt).strftime("%H:%M")
        except ValueError:
            continue
    return text[-5:] if len(text) >= 5 else text


def _api_headers():
    api_key = get_haccp_api_key()
    return {"X-API-Key": api_key} if api_key else {}


def _safe_float(value, default=None):
    try:
        if value in (None, "", "None"):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _normalize_sensor_rows(payload):
    if isinstance(payload, dict):
        rows = payload.get("data") or payload.get("items") or payload.get("results") or []
        if not rows and any(key in payload for key in ("batch_id", "temperature_celsius", "temperature", "pH", "flow_in_lpm", "flow_out_lpm")):
            rows = [payload]
    elif isinstance(payload, list):
        rows = payload
    else:
        rows = []

    normalized_rows = []
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            continue
        timestamp = row.get("time") or row.get("timestamp") or row.get("datetime") or row.get("created_at") or datetime.now().isoformat(timespec="seconds")
        normalized_rows.append(
            {
                "idx": index,
                "timestamp": timestamp,
                "time_label": _parse_time_label(timestamp),
                "batch_id": row.get("batch_id") or row.get("process_id") or row.get("line") or f"ROW-{index + 1}",
                "line_id": row.get("line_id"),
                "line_run": row.get("line_run"),
                "line_day": row.get("line_day"),
                "state": str(row.get("state") or row.get("stage") or row.get("status") or "").strip(),
                "temperature": _safe_float(row.get("temperature") or row.get("temperature_celsius") or row.get("temp") or row.get("T")),
                "ph": _safe_float(row.get("ph") or row.get("pH")),
                "density": _safe_float(row.get("density") or row.get("mu") or row.get("Mu")),
                "tau": _safe_float(row.get("tau") or row.get("Tau")),
                "T_z": _safe_float(row.get("T_z") or row.get("temp_z") or row.get("temperature_z")),
                "pH_z": _safe_float(row.get("pH_z") or row.get("ph_z")),
                "Mu_z": _safe_float(row.get("Mu_z") or row.get("mu_z") or row.get("density_z")),
                "Tau_z": _safe_float(row.get("Tau_z") or row.get("tau_z")),
                "warning_score": _safe_float(row.get("warning_score") or row.get("risk_score") or row.get("predicted_risk"), 0.0) or 0.0,
                "ccp_hold_temp_ok": int(_safe_float(row.get("ccp_hold_temp_ok"), 1.0) or 0),
                "ccp_hold_time_ok": int(_safe_float(row.get("ccp_hold_time_ok"), 1.0) or 0),
                "process_completed": bool(row.get("process_completed") or row.get("completed")),
            }
        )
    return normalized_rows


def _is_process_completed(row):
    state = str(row.get("state") or "").lower()
    return bool(row.get("process_completed")) or state in {"complete", "completed", "discharge", "release", "done"}

def _make_alert(
    level,
    message,
    time_value,
    source,
    *,
    line_id=None,
    batch_id=None,
    stage=None,
    event_type=None,
    status=None,
    meta: dict | None = None,
):
    occurred_at = time_value or datetime.now().isoformat(timespec="seconds")
    return {
        "id": _alert_id(level, message, occurred_at, source),
        "level": level,
        "message": message,
        "occurred_at": occurred_at,
        "time": _parse_time_label(occurred_at),
        "source": source,
        "event_type": event_type,
        "status": status,
        "line_id": line_id,
        "batch_id": batch_id,
        "stage": stage,
        "meta": meta or {},
    }


def _fallback_alerts():
    return [
        _make_alert("위험", "BATCH-054 가열 살균 공정에서 CCP 보온 온도 하한 이탈이 확인되었습니다. 출하 보류 후 원인 점검이 필요합니다.", "2026-04-16 09:41:00", "fallback-danger"),
        _make_alert("경고", "BATCH-112 냉각 단계에서 정상 범위 이탈 징후가 감지되었습니다. 품질 영향 전 사전 확인이 필요합니다.", "2026-04-16 09:36:00", "fallback-warning"),
        _make_alert("정보", "BATCH-001 공정이 완료되어 QAQC 검토 및 최종 출하 판단 대기 상태로 전환되었습니다.", "2026-04-16 09:28:00", "fallback-info"),
    ]


def _build_business_alerts(sensor_rows):
    alerts = []
    completed_batches = set()

    for row in sensor_rows:
        batch_id = row.get("batch_id")
        line_id = row.get("line_id")
        stage = row.get("state")
        timestamp = row.get("timestamp") or datetime.now().isoformat(timespec="seconds")
        warning_score = row.get("warning_score") or 0.0
        decision = classify_heating_sensor_row(row)

        if _is_process_completed(row) and batch_id not in completed_batches:
            completed_batches.add(batch_id)
            alerts.append(_make_alert("정보", f"공정 완료: {batch_id} 배치가 정상 완료되었습니다.", timestamp, "complete"))

        if decision.ccp_ok is False:
            alerts.append(_make_alert("위험", f"CCP 이탈: {batch_id} 배치(살균 온도/유지시간) 즉시 확인/조치 필요", timestamp, "ccp-danger"))

        if decision.warning_metrics:
            metrics_text = ", ".join(
                {"pH_z": "pH", "Mu_z": "점도", "Tau_z": "Kappa(전기전도도)"}.get(m, m)
                for m in decision.warning_metrics[:3]
            )
            alerts.append(_make_alert("경고", f"물성 이상(CCP 연계): {batch_id} 배치 {metrics_text} 정상 범위 이탈", timestamp, "sensor-warning"))
        # 주의 단계는 정상으로 통합 (별도 알람 미발행)

        if warning_score >= 0.75 and decision.level == "정상":
            alerts.append(_make_alert("경고", f"사전 경고: {batch_id} 배치에서 정상 범위 이탈 징후가 감지되었습니다.", timestamp, "predict-warning"))

    deduped_alerts = {}
    for alert in alerts:
        deduped_alerts[alert["id"]] = alert
    return list(deduped_alerts.values())


def get_sensor_data(force_refresh=False):
    """API에서 센서 데이터 가져오기"""
    now = monotonic()
    if not force_refresh and _sensor_cache["data"] and _sensor_cache["expires_at"] > now:
        return _clone_runtime_items(_sensor_cache["data"])

    sensor_url = f"{get_api_base_url()}/api/sensor-data"
    try:
        connect_timeout, read_timeout = get_api_timeouts()
        response = _http_get(sensor_url, headers=_api_headers(), timeout=(connect_timeout, read_timeout))
        response.raise_for_status()
        sensor_rows = _normalize_sensor_rows(response.json())
        _sensor_cache["data"] = sensor_rows
        _sensor_cache["expires_at"] = monotonic() + RUNTIME_API_CACHE_TTL_SECONDS
        _set_runtime_api_status(sensor_ok=True, sensor_error="")
        return _clone_runtime_items(sensor_rows)
    except Exception as exc:
        _set_runtime_api_status(
            sensor_ok=False,
            sensor_error=f"센서 API 오류: {_describe_requests_error(exc, sensor_url)}",
        )
        if _sensor_cache["data"]:
            return _clone_runtime_items(_sensor_cache["data"])

        # Remote API가 완전히 불가한 경우에도 대시보드가 "실시간 공정"처럼 동작하도록
        # 공정 CSV(150배치)에서 현재 시점의 라인별 센서 행을 생성해 폴백한다.
        try:
            fallback_rows = build_local_sensor_rows()
            _sensor_cache["data"] = fallback_rows
            _sensor_cache["expires_at"] = monotonic() + RUNTIME_API_CACHE_TTL_SECONDS
            return _clone_runtime_items(fallback_rows)
        except Exception:
            return _clone_runtime_items(_sensor_cache["data"])


def get_alert_data(sensor_rows=None, force_refresh=False):
    """원격 알람과 비즈니스 알람을 합쳐 반환"""
    now = monotonic()
    if sensor_rows is None and not force_refresh and _alert_cache["data"] and _alert_cache["expires_at"] > now:
        return _clone_runtime_items(_alert_cache["data"])

    sensor_rows = sensor_rows if sensor_rows is not None else get_sensor_data(force_refresh=force_refresh)
    merged_alerts = {}
    alerts_url = f"{get_api_base_url()}/api/alerts"

    try:
        connect_timeout, read_timeout = get_api_timeouts()
        response = _http_get(alerts_url, headers=_api_headers(), timeout=(connect_timeout, read_timeout))
        response.raise_for_status()
        data = response.json()
        if isinstance(data, dict):
            data = data.get("alerts", [])
        if isinstance(data, list):
            for item in data:
                if not isinstance(item, dict):
                    continue
                alert = _make_alert(item.get("level", "정보"), item.get("message", "알림"), item.get("time"), "api")
                merged_alerts[alert["id"]] = alert
        _set_runtime_api_status(alerts_ok=True, alerts_error="")
    except Exception as exc:
        _set_runtime_api_status(
            alerts_ok=False,
            alerts_error=f"알람 API 오류: {_describe_requests_error(exc, alerts_url)}",
        )
        data = []

    for alert in _build_business_alerts(sensor_rows):
        merged_alerts[alert["id"]] = alert

    alerts = list(merged_alerts.values())
    if not alerts:
        alerts = _fallback_alerts()
    alerts.sort(key=lambda item: str(item.get("occurred_at") or item.get("time") or ""), reverse=True)
    _alert_cache["data"] = alerts
    _alert_cache["expires_at"] = monotonic() + RUNTIME_API_CACHE_TTL_SECONDS

    # Persist alerts as a cumulative operational log (best-effort).
    try:
        from haccp_dashboard.db_store import insert_alert_event

        for alert in alerts:
            if isinstance(alert, dict):
                insert_alert_event(alert, source="runtime")
    except Exception:
        pass

    return _clone_runtime_items(alerts)


def _format_ai_answer(ccp_status, risk_level, cause, action_steps, extra_lines=None):
    sections = [
        f"1) CCP 기준 여부: {ccp_status}",
        f"2) 위험 수준: {risk_level}",
        f"3) 원인: {cause}",
        f"4) 조치 순서: {action_steps}",
    ]
    if extra_lines:
        sections.extend(str(line) for line in extra_lines if line)
    return "\n".join(sections)


def _get_latest_heating_summary():
    try:
        from .dashboard_demo import get_batch_summary_frame
    except ImportError:
        from dashboard_demo import get_batch_summary_frame

    summary = get_batch_summary_frame()
    if summary.empty:
        return None
    return summary.sort_values(["date", "batch_id"], ascending=[False, False]).iloc[0]


def _get_latest_sensor_snapshot(sensor_rows=None):
    sensor_rows = sensor_rows if sensor_rows is not None else get_sensor_data()
    if sensor_rows:
        return sensor_rows[-1]
    return None


def _build_local_ai_report(sensor_rows=None, alerts=None):
    summary_row = _get_latest_heating_summary()
    sensor_row = _get_latest_sensor_snapshot(sensor_rows)
    alerts = alerts if alerts is not None else get_alert_data(sensor_rows=sensor_rows)
    danger_alerts = [alert for alert in alerts if alert.get("level") == "위험"]
    warning_alerts = [alert for alert in alerts if alert.get("level") == "경고"]

    if summary_row is None:
        return "현재 보고서를 생성할 배치 데이터가 없습니다. 센서 또는 공정 데이터 적재 상태를 먼저 확인해 주세요."

    ccp_status = "충족" if summary_row["hold_temp_ok"] and summary_row["hold_time_ok"] else "일부 이탈"
    risk_level = f"{summary_row['risk_level']} ({summary_row['batch_name']}, 안정도 {summary_row['stability_score']:.1f}%)"
    cause = (
        f"최고온도 {summary_row['peak_temp']:.1f}℃, 최종온도 {summary_row['final_temp']:.1f}℃, pH {summary_row['final_ph']:.2f}, "
        f"오염 판정 {summary_row['contamination_label']} 기준으로 계산되었습니다."
    )
    action_steps = (
        "고위험 알람 확인 → 해당 배치 출하 보류 여부 검토 → 살균/보온 조건 재확인 → 품질팀 확인 후 해제 또는 재처리 결정"
    )

    extra_lines = [
        f"- 알람 현황: 위험 {len(danger_alerts)}건, 경고 {len(warning_alerts)}건",
        f"- 최신 배치: {summary_row['batch_name']} / 상태 {summary_row['status']} / 보온 {summary_row['hold_minutes']:.1f}분",
    ]
    if sensor_row:
        sensor_temp = sensor_row.get("temperature")
        sensor_ph = sensor_row.get("ph")
        sensor_state = sensor_row.get("state") or "미상"
        sensor_bits = [f"단계 {sensor_state}"]
        if sensor_temp is not None:
            sensor_bits.append(f"온도 {sensor_temp:.1f}℃")
        if sensor_ph is not None:
            sensor_bits.append(f"pH {sensor_ph:.2f}")
        extra_lines.append(f"- 최신 센서 스냅샷: {' / '.join(sensor_bits)}")

    return _format_ai_answer(ccp_status, risk_level, cause, action_steps, extra_lines)


def _contains_ccp_keyword(text):
    normalized = str(text or "").lower().replace("haccp", " ")
    return "ccp" in normalized or "중요관리점" in normalized or "중요 관리점" in normalized


def _build_local_ai_response(msg, sensor_rows=None, alerts=None):
    text = str(msg or "").strip()
    if not text:
        return ""

    lowered = text.lower()
    summary_row = _get_latest_heating_summary()
    sensor_row = _get_latest_sensor_snapshot(sensor_rows)
    if alerts is None:
        resolved_sensor_rows = sensor_rows if sensor_rows is not None else ([sensor_row] if sensor_row else None)
        alerts = get_alert_data(sensor_rows=resolved_sensor_rows)
    danger_alerts = [alert for alert in alerts if alert.get("level") == "위험"]
    warning_alerts = [alert for alert in alerts if alert.get("level") == "경고"]

    if any(keyword in lowered for keyword in ["보고서", "리포트", "요약", "정리"]):
        return _build_local_ai_report(sensor_rows=sensor_rows, alerts=alerts)

    if any(keyword in lowered for keyword in ["알람", "경고", "위험", "이상"]):
        latest_danger = danger_alerts[0]["message"] if danger_alerts else "현재 위험 알람은 없습니다."
        latest_warning = warning_alerts[0]["message"] if warning_alerts else "현재 경고 알람은 없습니다."
        return _format_ai_answer(
            f"위험 {len(danger_alerts)}건, 경고 {len(warning_alerts)}건 모니터링 중",
            "위험" if danger_alerts else "경고" if warning_alerts else "정상",
            f"최근 위험 알람: {latest_danger}",
            "위험 알람 우선 확인 → 원인 설비 점검 → 출하 영향 여부 판정 → 조치 결과 기록",
            [f"- 최근 경고 알람: {latest_warning}"],
        )

    if any(keyword in lowered for keyword in ["ph", "산도"]):
        current_ph = sensor_row.get("ph") if sensor_row else (float(summary_row["final_ph"]) if summary_row is not None else None)
        if current_ph is None:
            return _format_ai_answer("판단 불가", "정보", "현재 pH 데이터가 없습니다.", "센서 연결 상태 확인 → 최근 배치 기록 재조회")
        current_ph_z = sensor_row.get("pH_z") if sensor_row else None
        if current_ph_z is None:
            return _format_ai_answer(
                "CCP 아님(운영지표)",
                "정보",
                f"현재 pH {current_ph:.2f} 값은 확보했지만, 편차(z-score) 지표가 없어 자동 경고/위험 판정은 제한됩니다.",
                "센서 스키마에 pH_z 추가(또는 기준선/표준편차 전달) → 안정도 기준으로 경고/위험 자동화",
            )

        abs_z = abs(float(current_ph_z))
        if abs_z >= HEATING_DANGER_Z_ABS:
            risk_level = "위험"
        elif abs_z >= HEATING_WARNING_Z_ABS:
            risk_level = "경고"
        else:
            risk_level = "정상"

        cause = f"현재 pH {current_ph:.2f}이며 pH 편차 z={float(current_ph_z):.2f} (경고≥{HEATING_WARNING_Z_ABS:.0f}, 위험≥{HEATING_DANGER_Z_ABS:.0f}) 기준으로 판정했습니다."
        action_steps = "센서 교정 확인 → 원유/배합 이력 확인 → 해당 배치 격리/보류 여부 판단 → 재검사 결과 기록"
        return _format_ai_answer("CCP 아님(운영지표)", risk_level, cause, action_steps)

    if any(keyword in lowered for keyword in ["인증 취소", "인증취소", "부적합", "인증", "해썹 인증"]) or "haccp" in lowered:
        latest_batch_text = "최근 배치 데이터가 없습니다."
        if summary_row is not None:
            latest_batch_text = f"최근 배치 {summary_row['batch_name']}은 상태 {summary_row['status']} / 위험도 {summary_row['risk_level']}입니다."
        return _format_ai_answer(
            "중대한 부적합 누적 시 인증 유지 곤란",
            "위험" if danger_alerts else "경고",
            "반복적인 CCP 미준수, 기록 위변조, 시정조치 미이행, 위해 제품 출하, 내부 검증 실패가 누적되면 인증 취소 또는 중대한 부적합으로 이어질 수 있습니다.",
            "중대 부적합 즉시 격리 → 원인조사 및 CAPA 수립 → 기록 보완 → 내부검증 재실시 → 심사 대응 자료 정리",
            [f"- {latest_batch_text}", f"- 현재 위험 알람 {len(danger_alerts)}건 / 경고 알람 {len(warning_alerts)}건"],
        )

    if any(keyword in lowered for keyword in ["냉장", "허용 시간", "허용시간", "초과 제품", "격리", "폐기", "재검사"]):
        return _format_ai_answer(
            "냉장 허용 시간 초과 시 보류 후 판정",
            "위험" if danger_alerts else "경고",
            "냉장 유지 한계를 넘긴 제품은 미생물 증식 위험 때문에 즉시 정상 출하 대상으로 보기 어렵습니다.",
            "해당 제품 즉시 격리 → 시간/온도 이력 확인 → 재냉각 또는 재작업 가능성 검토 → 품질 재검사 → 출하/폐기 판정",
            [f"- 최신 위험 알람: {danger_alerts[0]['message'] if danger_alerts else '없음'}"],
        )

    if any(keyword in lowered for keyword in ["기록 보존", "보존 기간", "보존기간", "기록 관리", "문서 보관"]):
        return _format_ai_answer(
            "법규 및 내부 기준에 따른 장기 보존 필요",
            "경고",
            "HACCP 기록은 공정기록, 점검기록, 시정조치, 검증자료가 서로 연결되어야 하며, 누락되면 추적성과 심사 대응력이 떨어집니다.",
            "기록 종류별 보존 기준 확인 → 전자/종이 원본 분리 관리 → 배치번호와 연결 → 수정 이력 관리 → 정기 백업",
            ["- 실제 보존 연한은 회사 내부 기준과 적용 법규를 함께 확인해야 합니다."],
        )

    if _contains_ccp_keyword(lowered):
        if summary_row is None:
            return _format_ai_answer("판단 불가", "정보", "현재 가열 공정 요약 데이터가 없습니다.", "데이터 적재 상태 확인 후 다시 조회")
        ccp_status = "충족" if summary_row["hold_temp_ok"] and summary_row["hold_time_ok"] else "이탈"
        risk_level = "위험" if ccp_status == "이탈" else "정상"
        cause = (
            f"CCP 판단은 {summary_row['batch_name']} 기준으로 살균 최고온도 {summary_row['peak_temp']:.1f}℃, "
            f"보온 {summary_row['hold_minutes']:.1f}분, 최종온도 {summary_row['final_temp']:.1f}℃, 오염 판정 {summary_row['contamination_label']}를 함께 봐야 합니다."
        )
        action_steps = "1차로 온도 기준 확인 → 2차로 보온시간 확인 → 3차로 센서/기록 신뢰성 점검 → 4차로 출하 영향 여부와 시정조치 판단"
        extra_lines = [
            f"- 최신 배치 상태: {summary_row['status']} / 안정도 {summary_row['stability_score']:.1f}%",
        ]
        return _format_ai_answer(ccp_status, risk_level, cause, action_steps, extra_lines)

    if any(keyword in lowered for keyword in ["가열", "살균", "보온", "배치", "온도"]):
        if summary_row is None:
            return _format_ai_answer("판단 불가", "정보", "현재 가열 공정 요약 데이터가 없습니다.", "데이터 적재 상태 확인 후 다시 조회")
        ccp_status = "충족" if summary_row["hold_temp_ok"] and summary_row["hold_time_ok"] else "이탈"
        risk_level = summary_row["risk_level"]
        cause = (
            f"{summary_row['batch_name']} 기준 최고온도 {summary_row['peak_temp']:.1f}℃, 최종온도 {summary_row['final_temp']:.1f}℃, "
            f"보온 {summary_row['hold_minutes']:.1f}분, 오염 판정 {summary_row['contamination_label']}입니다."
        )
        action_steps = "살균 최고온도 확인 → 보온시간 확인 → 냉각 완료 여부 확인 → 출하 가능/보류 판정 → CAPA 기록"
        extra_lines = [
            f"- 최신 배치 상태: {summary_row['status']} / 안정도 {summary_row['stability_score']:.1f}% / 마지막 단계 {summary_row['last_state']}",
        ]
        return _format_ai_answer(ccp_status, risk_level, cause, action_steps, extra_lines)

    overall_risk = "위험" if danger_alerts else "경고" if warning_alerts else "정상"
    if summary_row is not None:
        cause = (
            f"최신 기준 배치는 {summary_row['batch_name']}이고 상태는 {summary_row['status']}, "
            f"안정도는 {summary_row['stability_score']:.1f}%입니다."
        )
    else:
        cause = "현재 불러온 배치 요약 데이터가 없어 일반 기준으로만 안내합니다."

    return _format_ai_answer(
        "질문 유형에 따라 판단",
        overall_risk,
        cause,
        "질문을 더 구체화해 주세요. 예: 살균 온도 이탈 조치, pH 이탈 원인, 오늘 보고서 요약",
        ["- 현재 AI는 내부 데이터와 규칙 기반 답변을 우선 제공하고, OpenAI 키가 있으면 외부 모델 답변으로 확장됩니다."],
    )


def ai_response(msg, sensor_rows=None, alerts=None):
    """OpenAI API로 HACCP 전문가 응답 생성"""
    if not msg or msg.strip() == "":
        return ""
    ai_client = get_openai_client()
    if not ai_client:
        return _build_local_ai_response(msg, sensor_rows=sensor_rows, alerts=alerts)
    try:
        response = ai_client.chat.completions.create(
            model=get_openai_chat_model(),
            messages=[
                {
                    "role": "system",
                    "content": (
                        "너는 HACCP 품질관리 전문가다. "
                        "답변은 실무적으로 짧고 명확하게 작성하고, 1) CCP 기준 여부 2) 위험 수준 3) 원인 4) 조치 순서로 설명한다."
                    )
                },
                {"role": "user", "content": msg},
            ],
            temperature=0.3,
            max_tokens=320,
            timeout=get_openai_timeout_seconds(),
        )
        return response.choices[0].message.content
    except Exception as error:
        fallback = _build_local_ai_response(msg, sensor_rows=sensor_rows, alerts=alerts)
        error_text = str(error)
        if "api key" in error_text.lower() or "401" in error_text.lower() or "unauthorized" in error_text.lower():
            return fallback
        return f"{fallback}\n\n참고: 외부 AI 호출 실패로 로컬 분석 답변을 제공했습니다."


def send_to_slack(msg):
    """Slack 채널에 메시지 전송"""
    if not msg or not msg.strip():
        return False, "메시지를 입력해주세요."
    client = _ensure_slack_client()
    if not client:
        return False, "Slack SDK 또는 SLACK_BOT_TOKEN이 없어 로컬 미리보기로만 표시됩니다."
    if not SLACK_CHANNEL_ID:
        return False, "Slack 채널 설정이 없어 메시지를 전송할 수 없습니다."
    try:
        client.chat_postMessage(channel=SLACK_CHANNEL_ID, text=msg)
        return True, "Slack 메시지를 전송했습니다."
    except SlackApiError as error:
        error_message = error.response.get("error", str(error)) if hasattr(error, "response") else str(error)
        return False, f"Slack 전송 실패: {error_message}"
    except Exception as error:
        return False, f"Slack 전송 실패: {str(error)[:120]}"


def get_slack_messages(local_messages=None):
    """Slack 메시지 가져오기"""
    seeded_messages = list(DEFAULT_DM_MESSAGES)
    if local_messages:
        seeded_messages.extend(local_messages)

    client = _ensure_slack_client()
    if not client:
        return seeded_messages, "Slack SDK 또는 토큰이 없어 샘플 QAQC 메시지와 로컬 메시지만 표시합니다.", "warning"
    if not SLACK_CHANNEL_ID:
        return seeded_messages, "Slack 채널 설정이 없어 로컬 메시지만 표시합니다.", "warning"
    try:
        response = client.conversations_history(channel=SLACK_CHANNEL_ID, limit=20)
        messages = response.get("messages", [])
        result = []
        for message in reversed(messages):
            user_id = message.get("user") or message.get("username") or "Slack"
            result.append(
                {
                    "user": user_id,
                    "text": message.get("text", ""),
                    "time": _parse_time_label(message.get("ts")),
                    "is_me": bool(SLACK_USER_ID and user_id == SLACK_USER_ID),
                }
            )
        return seeded_messages + result, "Slack 연결 정상", "info"
    except SlackApiError as error:
        error_message = error.response.get("error", str(error)) if hasattr(error, "response") else str(error)
        return seeded_messages, f"Slack 조회 실패: {error_message}", "danger"
    except Exception as error:
        return seeded_messages, f"Slack 조회 실패: {str(error)[:120]}", "danger"


def alarm_item(alert, is_read=False, prefix="alarm-item"):
    """알람 아이템 UI 생성"""
    color_map = {
        "경고": {"bg": "#fef3c7", "border": "#fbbf24", "text": "#b45309"},
        "정보": {"bg": "#dbeafe", "border": "#60a5fa", "text": "#1d4ed8"},
        "위험": {"bg": "#fee2e2", "border": "#f87171", "text": "#b91c1c"},
    }
    colors = color_map.get(alert["level"], {"bg": "#f3f4f6", "border": "#d1d5db", "text": "#374151"})

    return html.Button(
        id={"type": prefix, "index": alert["id"]},
        n_clicks=0,
        style={
            "width": "100%",
            "background": colors["bg"],
            "padding": "12px 14px",
            "borderLeft": f"4px solid {colors['border']}",
            "border": "none",
            "borderRadius": "12px",
            "marginBottom": "8px",
            "display": "flex",
            "justifyContent": "space-between",
            "alignItems": "center",
            "cursor": "pointer",
            "transition": "all 0.22s ease",
            "fontSize": "13px",
            "opacity": "0.62" if is_read else "1",
            "textAlign": "left",
        },
        children=[
            html.Div(
                [
                    html.Span(
                        alert["level"],
                        style={
                            "background": colors["border"],
                            "color": "white",
                            "padding": "4px 8px",
                            "borderRadius": "999px",
                            "fontSize": "11px",
                            "fontWeight": "700",
                            "marginRight": "8px",
                        },
                    ),
                    html.Span(alert["message"], style={"color": "#1f2937", "lineHeight": "1.45"}),
                ],
                style={"flex": 1},
            ),
            html.Div(
                [
                    html.Div(alert["time"], style={"fontSize": "11px", "color": "#6b7280", "whiteSpace": "nowrap"}),
                    html.Div("읽음" if is_read else "새 알림", style={"fontSize": "10px", "color": colors["text"], "fontWeight": "700", "marginTop": "4px"}),
                ],
                style={"marginLeft": "10px", "textAlign": "right"},
            ),
        ],
    )


def kakao_bubble(user, text, is_me=False, time_label=""):
    """카카오톡 스타일 채팅 bubble UI"""
    return html.Div(
        style={"display": "flex", "justifyContent": "flex-end" if is_me else "flex-start", "marginBottom": "8px"},
        children=[
            html.Div(
                [
                    html.Div(user, style={"fontSize": "11px", "color": "#6b7280", "marginBottom": "4px", "textAlign": "right" if is_me else "left"}),
                    html.Div(
                        text,
                        style={
                            "background": "#fef3c7" if is_me else "white",
                            "padding": "8px 12px",
                            "borderRadius": "15px",
                            "maxWidth": "100%",
                            "fontSize": "13px",
                            "border": "1px solid #ececec",
                        },
                    ),
                    html.Div(time_label, style={"fontSize": "10px", "color": "#94a3b8", "textAlign": "right" if is_me else "left", "marginTop": "3px"}),
                ],
                style={"maxWidth": "78%"},
            )
        ],
    )


def ai_chat_bubble(role, text):
    is_user = role == "user"
    return html.Div(
        style={"display": "flex", "justifyContent": "flex-end" if is_user else "flex-start", "marginBottom": "8px"},
        children=[
            html.Div(
                text,
                style={
                    "background": "#2563eb" if is_user else "#f3f4f6",
                    "color": "white" if is_user else "#111827",
                    "padding": "10px 12px",
                    "borderRadius": "15px",
                    "maxWidth": "82%",
                    "fontSize": "13px",
                    "lineHeight": "1.55",
                    "whiteSpace": "pre-wrap",
                },
            )
        ],
    )


def build_status_banner(text, level="info"):
    palette = {
        "info": ("#eff6ff", "#1d4ed8", "#bfdbfe"),
        "warning": ("#fffbeb", "#b45309", "#fde68a"),
        "danger": ("#fef2f2", "#b91c1c", "#fecaca"),
        "success": ("#f0fdf4", "#166534", "#bbf7d0"),
    }
    bg, text_color, border = palette.get(level, palette["info"])
    return html.Div(
        text,
        style={
            "background": bg,
            "color": text_color,
            "border": f"1px solid {border}",
            "borderRadius": "12px",
            "padding": "10px 12px",
            "fontSize": "12px",
            "lineHeight": "1.5",
        },
    )


def build_ai_assistant_sidebar():
    """AI 어시스턴트 사이드바 UI"""
    ai_banner = build_status_banner(
        "OpenAI 키 없이도 내부 데이터 기반 답변을 제공합니다." if not AI_CLIENT else "AI 연결 정상. 빠른 질문 또는 직접 질문을 사용할 수 있습니다.",
        "info" if not AI_CLIENT else "success",
    )

    return html.Div(
        id="ai-sidebar",
        style={
            "width": f"{AI_EXPANDED_WIDTH}px",
            "position": "fixed",
            "right": "0",
            "top": f"{HEADER_HEIGHT}px",
            "height": f"calc(100vh - {HEADER_HEIGHT}px)",
            "background": "white",
            "borderLeft": "1px solid #e5e7eb",
            "display": "flex",
            "flexDirection": "column",
            "zIndex": "1000",
            "transition": "width 0.28s ease",
            "overflow": "hidden",
        },
        children=[
            html.Div(
                [
                    html.Div(id="ai-sidebar-title", children="🤖 AI 어시스턴트", style={"fontWeight": "bold", "color": "#1f2937"}),
                    html.Button(
                        "⟩",
                        id="collapse-ai-btn",
                        n_clicks=0,
                        style={
                            "background": "none",
                            "border": "none",
                            "fontSize": "18px",
                            "cursor": "pointer",
                            "color": "#6b7280",
                            "padding": "4px 8px",
                            "borderRadius": "8px",
                        },
                    ),
                ],
                style={
                    "display": "flex",
                    "justifyContent": "space-between",
                    "alignItems": "center",
                    "padding": "15px",
                    "borderBottom": "1px solid #eee",
                },
            ),
            html.Div(
                id="ai-sidebar-content",
                style={"display": "flex", "flexDirection": "column", "height": "100%"},
                children=[
                    html.Div(ai_banner, id="ai-banner", style={"padding": "10px 10px 0 10px"}),
                    html.Div(build_status_banner("실시간 API 상태 확인 중입니다.", "info"), id="runtime-api-banner", style={"padding": "10px 10px 0 10px"}),
                    html.Div(id="chat", style={"flex": "1", "padding": "10px", "overflowY": "auto", "display": "flex", "flexDirection": "column"}),
                    html.Div(
                        [
                            html.Div("빠른 질문", style={"fontSize": "12px", "color": "#6b7280", "marginBottom": "8px", "fontWeight": "500"}),
                            html.Div(
                                [
                                    html.Button("살균 온도 이탈 조치", id="q1", n_clicks=0, className="quick-btn"),
                                    html.Button("CCP 기준 판단", id="q2", n_clicks=0, className="quick-btn"),
                                    html.Button("냉장 초과 제품 처리", id="q3", n_clicks=0, className="quick-btn"),
                                    html.Button("pH 이탈 원인 조치", id="q4", n_clicks=0, className="quick-btn"),
                                    html.Button("인증 취소 기준", id="q5", n_clicks=0, className="quick-btn"),
                                    html.Button("냉장 허용 시간 기준", id="q6", n_clicks=0, className="quick-btn"),
                                ],
                                style={"display": "grid", "gridTemplateColumns": "1fr 1fr", "gap": "10px", "marginTop": "6px"},
                            ),
                        ],
                        style={"padding": "10px"},
                    ),
                    html.Div(
                        [
                            dcc.Input(id="input", placeholder="궁금한 점을 질문해 보세요.", style={
                                "flex": "1", "border": "1px solid #e5e7eb", "borderRadius": "10px", "padding": "10px", "fontSize": "13px"
                            }),
                            html.Button("전송", id="btn", n_clicks=0, style={
                                "marginLeft": "6px", "background": "#3b82f6", "color": "white",
                                "border": "none", "padding": "10px 12px", "borderRadius": "8px", "cursor": "pointer"
                            }),
                        ],
                        style={"display": "flex", "padding": "10px", "borderTop": "1px solid #eee"},
                    ),
                ],
            ),
        ],
    )


def _build_kpi_cards(kpi_items: list[dict]) -> list:
    from dash_iconify import DashIconify
    cards = []
    for item in kpi_items or []:
        cards.append(
            html.Div(
                [
                    html.Div(
                        [
                            html.Div(
                                DashIconify(icon=item.get("icon") or "mdi:chart-box-outline", width=22),
                                className="kpi-icon",
                            ),
                            html.Div(item.get("title", "-"), className="kpi-label"),
                        ],
                        className="kpi-top",
                    ),
                    html.Div(item.get("value", "-"), className="kpi-value"),
                    html.Div(item.get("description", ""), className="kpi-description"),
                ],
                className="kpi-card",
                style={"--kpi-accent": item.get("accent", "#3498db")},
            )
        )
    return cards


def build_main_layout(_frame: pd.DataFrame | None = None):
    return html.Div(
        [
            html.Div(
                [
                    html.Div(
                        [
                            html.H1("QA/QC 운영 현황", style={"marginBottom": "22px", "fontSize": "28px", "fontWeight": "900", "color": "#111827"}),
                            html.Div(
                                [
                                    html.H2("일일 KPI", style={"marginBottom": "14px", "fontSize": "18px", "fontWeight": "900", "color": "#111827"}),
                                    html.Div(id="main-kpi-container", className="kpi-container", children=[]),
                                ],
                                style={"marginBottom": "18px"},
                            ),
                        ],
                        className="dashboard-left",
                    ),
                ],
                className="dashboard-grid",
            ),
        ],
        className="dashboard-container",
        style={"minWidth": "0"},
    )


# === UNIFIED_DASHBOARD_STATUS_API_V1 ===
# 모든 페이지(메인/가열/최종검사/알람)가 동일하게 사용하는
# 공통 상태 판정 + 오염지표 유사도 분석 API.
SIMILARITY_WARN_THRESHOLD = 0.48
SIMILARITY_DANGER_THRESHOLD = 0.75
STABILITY_WARN_THRESHOLD = 80.0
STABILITY_DANGER_THRESHOLD = 60.0

STATUS_COLORS = {
    "정상": {"bg": "#ecfdf5", "text": "#166534", "border": "#86efac", "accent": "#16a34a"},
    "주의": {"bg": "#f7fee7", "text": "#365314", "border": "#bef264", "accent": "#65a30d"},
    "경고": {"bg": "#fffbeb", "text": "#b45309", "border": "#fde68a", "accent": "#f59e0b"},
    "위험": {"bg": "#fef2f2", "text": "#991b1b", "border": "#fecaca", "accent": "#dc2626"},
}
STATUS_MESSAGES = {
    "정상": "정상적으로 운영 중입니다.",
    "주의": "물성 지표에서 경미한 이상징후가 감지되었습니다.",
    "경고": "공정은 진행 중이나 모니터링이 필요합니다.",
    "위험": "즉시 확인 및 조치가 필요합니다.",
}
STATUS_ACTION_TEXT = {
    "정상": "모니터링 유지",
    "주의": "물성 모니터링 강화",
    "경고": "모니터링 필요",
    "위험": "즉시 조치 필요",
}

# 물성 z-score 기반 판정 임계값
PROPERTY_WARNING_Z = 2.0   # pH/Kappa/점도 명확한 이탈 → 경고
PROPERTY_CAUTION_Z = 1.0   # pH/Kappa/점도 약한 이상징후 → 주의


def _clip_score(value):
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return 0.0


def _format_similarity(value):
    try:
        return f"{float(value):.2f}"
    except (TypeError, ValueError):
        return "0.00"


def _infer_stage_from_state(last_state):
    """CSV state 값을 오염 유사도 분석용 3단계(HeatUp/Hold/Cool)로 매핑.

    가열살균공정 페이지의 6단계 UI 표시와는 별개로,
    오염원 유사도 보너스 계산에는 HeatUp/Hold/Cool 3단계 분류를 사용합니다.
    """
    s = str(last_state or "").strip()
    # 가열 전 단계 (대기/충진) → HeatUp 보너스 적용
    if s in {"HeatUp", "Heat", "Standardize", "PastFill"}:
        return "HeatUp"
    # 살균 완료 후 단계 (배출/충진공정/검사/출하) → Cool 보너스 적용
    if s in {"Cool", "Discharge", "Fill", "Inspect", "Release"}:
        return "Cool"
    # 기본: 살균 유지(Hold) 단계
    return "Hold"


def predict_contamination_from_sensor(summary) -> str:
    """원본 contamination 정답 라벨을 쓰지 않고, 센서/공정값만으로 모델 예측값을 근사.
    반환: 'no' | 'chem' | 'bio'"""
    try:
        ph_value = float(summary.get("final_ph", 6.7))
    except (TypeError, ValueError):
        ph_value = 6.7
    try:
        mu_z = float(summary.get("max_abs_mu_z", 0.0) or 0.0)
    except (TypeError, ValueError):
        mu_z = 0.0
    try:
        tau_z = float(summary.get("max_abs_tau_z", 0.0) or 0.0)
    except (TypeError, ValueError):
        tau_z = 0.0
    try:
        hold_minutes = float(summary.get("hold_minutes", 15.0) or 0.0)
    except (TypeError, ValueError):
        hold_minutes = 15.0
    try:
        final_temp = float(summary.get("final_temp", 7.0) or 7.0)
    except (TypeError, ValueError):
        final_temp = 7.0
    hold_time_ok = bool(summary.get("hold_time_ok", True))
    hold_temp_ok = bool(summary.get("hold_temp_ok", True))

    ph_dev = max(abs(ph_value - 6.7) - 0.1, 0.0)
    ccp_fail = (not hold_time_ok) or (not hold_temp_ok)
    chem_signal = int(ph_dev >= 0.05) + int(mu_z >= 2.5) + int(tau_z >= 2.5)
    # final_temp > 8.0 은 냉각 완료 후에만 의미 있음.
    # 가열 중 온도(~72°C)가 8.0을 초과해도 bio 신호로 잘못 카운트되지 않도록
    # 30°C 이하인 경우(냉각 완료 범위)에만 냉각 온도 이탈로 판단.
    bio_signal = int(ccp_fail) + int(hold_minutes < 12.0) + int(8.0 < final_temp <= 30.0)
    if bio_signal >= 2:
        return "bio"
    if chem_signal >= 2:
        return "chem"
    return "no"


def contaminant_scores_from_summary(summary, stage, model_pred=None):
    """센서/공정값 + 단계 + 모델 예측을 종합한 오염원별 유사도(0~1).
    `summary['contamination']`(원본 정답)은 사용하지 않음."""
    def _f(key, default=0.0):
        try:
            return float(summary.get(key, default) if hasattr(summary, "get") else getattr(summary, key, default))
        except (TypeError, ValueError):
            return float(default)

    ph_value = _f("final_ph", 6.7)
    mu_risk = _clip_score(_f("max_abs_mu_z") / 6.0)
    tau_risk = _clip_score(_f("max_abs_tau_z") / 6.0)
    ph_acid = _clip_score((6.6 - ph_value) / 0.35)
    ph_alkali = _clip_score((ph_value - 6.8) / 0.35)
    temp_gap = _clip_score(abs(_f("peak_temp", 64.0) - 64.0) / 8.0)
    hold_short = _clip_score(max(0.0, 15.0 - _f("hold_minutes", 15.0)) / 6.0)
    # HeatUp 단계에서는 hold_minutes=0이 정상(아직 Hold 구간 미진입).
    # 이 단계에서 hold_short 패널티를 주면 E.coli/Salmonella 유사도 오탐 발생 → 0으로 고정.
    if stage == "HeatUp":
        hold_short = 0.0
    # final_temp는 냉각 단계에서만 냉각 출구 온도를 의미함.
    # HeatUp/Hold 단계에서는 가열 중 온도가 저장되므로 cool_risk를 0으로 고정.
    cool_risk = (_clip_score(max(0.0, _f("final_temp", 7.0) - 63.0) / 4.0)
                 if stage == "Cool" else 0.0)
    stability_risk = _clip_score((100.0 - _f("stability_score", 100.0)) / 60.0)
    hold_time_ok = bool(summary.get("hold_time_ok", True) if hasattr(summary, "get") else getattr(summary, "hold_time_ok", True))
    hold_temp_ok = bool(summary.get("hold_temp_ok", True) if hasattr(summary, "get") else getattr(summary, "hold_temp_ok", True))
    ccp_risk = 0.0 if (hold_time_ok and hold_temp_ok) else 1.0

    stage_bonus = {
        "HeatUp": {"NaOH": 0.18, "HNO3": 0.18, "E.coli": 0.04, "Salmonella": 0.04, "Listeria": 0.02},
        "Hold":   {"NaOH": 0.04, "HNO3": 0.04, "E.coli": 0.20, "Salmonella": 0.22, "Listeria": 0.08},
        "Cool":   {"NaOH": 0.03, "HNO3": 0.03, "E.coli": 0.08, "Salmonella": 0.10, "Listeria": 0.24},
    }.get(stage, {"NaOH": 0, "HNO3": 0, "E.coli": 0, "Salmonella": 0, "Listeria": 0})

    if model_pred is None:
        model_pred = predict_contamination_from_sensor(summary if hasattr(summary, "get") else dict(summary))

    contamination_bonus = {"NaOH": 0.0, "HNO3": 0.0, "E.coli": 0.0, "Salmonella": 0.0, "Listeria": 0.0}
    if model_pred == "chem":
        contamination_bonus["NaOH"] = 0.14
        contamination_bonus["HNO3"] = 0.14
    elif model_pred == "bio":
        contamination_bonus["E.coli"] = 0.12
        contamination_bonus["Salmonella"] = 0.12
        contamination_bonus["Listeria"] = 0.12

    return {
        "NaOH": _clip_score((ph_alkali * 0.46) + (mu_risk * 0.24) + (tau_risk * 0.18) + stage_bonus["NaOH"] + contamination_bonus["NaOH"]),
        "HNO3": _clip_score((ph_acid * 0.48) + (mu_risk * 0.18) + (tau_risk * 0.16) + stage_bonus["HNO3"] + contamination_bonus["HNO3"]),
        "E.coli": _clip_score((ccp_risk * 0.30) + (hold_short * 0.22) + (temp_gap * 0.14) + (stability_risk * 0.14) + stage_bonus["E.coli"] + contamination_bonus["E.coli"]),
        "Salmonella": _clip_score((ccp_risk * 0.32) + (hold_short * 0.18) + (temp_gap * 0.18) + (stability_risk * 0.12) + stage_bonus["Salmonella"] + contamination_bonus["Salmonella"]),
        "Listeria": _clip_score((cool_risk * 0.34) + (ccp_risk * 0.18) + (stability_risk * 0.16) + (hold_short * 0.10) + stage_bonus["Listeria"] + contamination_bonus["Listeria"]),
    }


def classify_batch_status(ccp_risk, top_score, stability_score=100.0, *,
                          ph_z=0.0, mu_z=0.0, tau_z=0.0):
    """살균공정 4단계 판정.

    위험: 핵심 CCP 이탈 (온도/유지시간)
    경고: 물성 지표(pH/Kappa/점도) 명확한 이탈  OR 오염 유사도 높음
    주의: 물성 지표 약한 이상징후  OR 유사도 중등
    정상: 모든 주요 지표 정상 패턴 내
    """
    try:
        ccp_val = float(ccp_risk)
    except (TypeError, ValueError):
        ccp_val = 0.0
    try:
        score_val = float(top_score)
    except (TypeError, ValueError):
        score_val = 0.0
    try:
        stab_val = float(stability_score)
    except (TypeError, ValueError):
        stab_val = 100.0
    try:
        max_prop_z = max(abs(float(ph_z)), abs(float(mu_z)), abs(float(tau_z)))
    except (TypeError, ValueError):
        max_prop_z = 0.0

    if ccp_val >= 1.0:
        level = "위험"
    elif (max_prop_z >= PROPERTY_WARNING_Z
          or score_val >= SIMILARITY_DANGER_THRESHOLD
          or stab_val < STABILITY_DANGER_THRESHOLD):
        level = "경고"
    else:
        level = "정상"
    return level, STATUS_MESSAGES[level], STATUS_ACTION_TEXT[level]


def _top_name_to_label(top_name, top_score):
    try:
        score = float(top_score)
    except (TypeError, ValueError):
        score = 0.0
    if score < SIMILARITY_WARN_THRESHOLD:
        return "정상"
    if top_name in ("NaOH", "HNO3"):
        return "화학"
    if top_name in ("E.coli", "Salmonella", "Listeria"):
        return "미생물"
    return "정상"


def resolve_similarity_contamination_view(row, stage=None, model_pred=None):
    """배치 요약 행 → 통일 유사도/상태 뷰.
    반환 dict: stage, similarity_scores, top_name, top_score, label, status, message, action, model_pred, ccp_risk"""
    def _get(key, default=None):
        if hasattr(row, "get"):
            try:
                v = row.get(key, default)
            except Exception:
                v = default
            return default if v is None else v
        return getattr(row, key, default)

    summary = {
        "final_ph": _get("final_ph", 6.7),
        "max_abs_mu_z": _get("max_abs_mu_z", 0.0),
        "max_abs_tau_z": _get("max_abs_tau_z", 0.0),
        "peak_temp": _get("peak_temp", 64.0),
        "final_temp": _get("final_temp", 7.0),
        "hold_minutes": _get("hold_minutes", 15.0),
        "stability_score": _get("stability_score", 100.0),
        "hold_time_ok": _get("hold_time_ok", True),
        "hold_temp_ok": _get("hold_temp_ok", True),
    }
    if stage is None:
        stage = _infer_stage_from_state(_get("last_state") or _get("current_stage") or "Hold")
    if model_pred is None:
        model_pred = predict_contamination_from_sensor(summary)

    similarity_scores = contaminant_scores_from_summary(summary, stage, model_pred=model_pred)
    top_name, top_score = max(similarity_scores.items(), key=lambda kv: kv[1])
    ccp_risk = 0.0 if (summary["hold_time_ok"] and summary["hold_temp_ok"]) else 1.0
    ph_z = float(_get("max_abs_ph_z", 0.0) or 0.0)
    mu_z = float(_get("max_abs_mu_z", 0.0) or 0.0)
    tau_z = float(_get("max_abs_tau_z", 0.0) or 0.0)
    level, message, action = classify_batch_status(
        ccp_risk, top_score, summary["stability_score"],
        ph_z=ph_z, mu_z=mu_z, tau_z=tau_z,
    )
    label = _top_name_to_label(top_name, top_score)
    return {
        "stage": stage,
        "similarity_scores": similarity_scores,
        "top_name": top_name,
        "top_score": float(top_score),
        "label": label,
        "status": level,
        "message": message,
        "action": action,
        "model_pred": model_pred,
        "ccp_risk": ccp_risk,
    }
# === /UNIFIED_DASHBOARD_STATUS_API_V1 ===


# === CURRENT_BATCH_STATE_BUILDER_V1 ===
def build_current_batch_state(row, line_label=None, override=None):
    """모든 페이지가 동일하게 참조하는 현재 batch 상태 객체.

    반환 필드:
      selected_line, selected_batch, current_stage, current_stage_label,
      final_ph, final_temp, peak_temp, hold_minutes, stability_score,
      hold_time_ok, hold_temp_ok, ccp_risk,
      model_pred, similarity_result{top_name, top_score, scores, label},
      sensor_status (정상/경고/위험), current_status, action_message, footer_text,
      color_set (bg/text/border/accent)
    """
    def _get(k, default=None):
        if hasattr(row, "get"):
            v = row.get(k, default)
        else:
            v = getattr(row, k, default)
        return default if v is None else v

    view = resolve_similarity_contamination_view(row)
    stage = str(_get("current_stage") or view["stage"])
    try:
        from haccp_dashboard.lib.process_spec import PROCESS_STAGE_LABELS as _LBL
    except Exception:
        _LBL = {}
    last_state = str(_get("last_state") or stage)
    current_stage_label = _LBL.get(last_state, _LBL.get(stage, last_state))

    state = {
        "selected_line": line_label or _get("line_label") or (f"Line {int(_get('line_id'))}" if _get("line_id") is not None else None),
        "selected_batch": int(_get("batch_id")) if _get("batch_id") is not None else None,
        "batch_name": _get("batch_name"),
        "current_stage": last_state,
        "current_stage_label": current_stage_label,
        "final_ph": float(_get("final_ph", 6.7) or 6.7),
        "final_temp": float(_get("final_temp", 7.0) or 7.0),
        "peak_temp": float(_get("peak_temp", 64.0) or 64.0),
        "hold_minutes": float(_get("hold_minutes", 15.0) or 15.0),
        "stability_score": float(_get("stability_score", 100.0) or 100.0),
        "hold_time_ok": bool(_get("hold_time_ok", True)),
        "hold_temp_ok": bool(_get("hold_temp_ok", True)),
        "ccp_risk": view["ccp_risk"],
        "model_pred": view["model_pred"],
        "similarity_result": {
            "top_name": view["top_name"],
            "top_score": view["top_score"],
            "scores": view["similarity_scores"],
            "label": view["label"],
        },
        "sensor_status": view["status"],
        "current_status": view["status"],
        "action_message": view["action"],
        "footer_text": view["message"],
        "color_set": STATUS_COLORS.get(view["status"], STATUS_COLORS["정상"]),
    }
    if isinstance(override, dict):
        state.update({k: v for k, v in override.items() if v is not None})
    return state
# === /CURRENT_BATCH_STATE_BUILDER_V1 ===
