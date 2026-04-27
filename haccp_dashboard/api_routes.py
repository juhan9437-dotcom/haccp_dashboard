"""
외부 대시보드 연동용 REST API 라우트
- GET /api/sensor-data  : 센서 실시간 데이터
- GET /api/alerts       : 알람 실시간 데이터

인증: HTTP Header  →  X-API-Key: <HACCP_API_KEY 환경변수 값>
"""

import json
import ipaddress
import os
import secrets
import time
import base64
from datetime import datetime
from functools import wraps

from flask import Blueprint, Response, current_app, jsonify, request, send_file, stream_with_context

# ── Blueprint 생성 ─────────────────────────────────────────────────────────────
bp = Blueprint("external_api", __name__, url_prefix="/api")

# ── API Key 로드 (환경변수 우선, 없으면 기본값 사용) ──────────────────────────
# Never hardcode API keys in source. Configure via env `HACCP_API_KEY` (or `API_KEY` in legacy setups).
_API_KEY: str = (os.environ.get("HACCP_API_KEY") or os.environ.get("API_KEY") or os.environ.get("EXTERNAL_API_KEY") or "").strip()
_STREAM_TOKEN: str = os.environ.get("HACCP_STREAM_TOKEN", "").strip()
_REQUIRE_STREAM_TOKEN: bool = os.environ.get("HACCP_REQUIRE_STREAM_TOKEN", "0").strip().lower() in {"1", "true", "yes", "on"}
_CORS_ALLOW_ORIGIN: str = os.environ.get("HACCP_CORS_ALLOW_ORIGIN", "*").strip() or "*"


def _get_request_ip():
    forwarded_for = (request.headers.get("X-Forwarded-For") or "").split(",", 1)[0].strip()
    return forwarded_for or (request.remote_addr or "")


def _is_private_or_loopback_ip(raw_ip):
    if not raw_ip:
        return False

    try:
        address = ipaddress.ip_address(raw_ip)
    except ValueError:
        return False

    return address.is_private or address.is_loopback


def _is_stream_authorized():
    provided_token = (request.args.get("stream_token") or "").strip()
    if _STREAM_TOKEN:
        if secrets.compare_digest(provided_token.encode(), _STREAM_TOKEN.encode()):
            return True
        if _REQUIRE_STREAM_TOKEN:
            return False

    return _is_private_or_loopback_ip(_get_request_ip())


def _apply_cors_headers(response):
    response.headers["Access-Control-Allow-Origin"] = _CORS_ALLOW_ORIGIN
    response.headers["Access-Control-Allow-Headers"] = "Content-Type, X-API-Key"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    return response


def _require_api_key(f):
    """X-API-Key 헤더를 검증하는 데코레이터 (타이밍 공격 방지)."""
    @wraps(f)
    def wrapper(*args, **kwargs):
        # If no key is configured, allow requests (useful for local/dev). Production should set HACCP_API_KEY.
        if not _API_KEY:
            return f(*args, **kwargs)
        provided = request.headers.get("X-API-Key", "")
        if not secrets.compare_digest(provided.encode(), _API_KEY.encode()):
            return jsonify({"error": "Unauthorized", "message": "유효하지 않은 API Key입니다."}), 401
        return f(*args, **kwargs)
    return wrapper


# ── /api/sensor-data ──────────────────────────────────────────────────────────
@bp.route("/sensor-data", methods=["GET"])
@_require_api_key
def sensor_data():
    """CSV 기반 최신 배치의 센서 스냅샷을 반환합니다."""
    try:
        payload = _build_latest_sensor_payload()
        return jsonify(payload), 200
    except Exception as exc:
        return jsonify({"error": "Internal Server Error", "message": str(exc)}), 500


# ── /api/alerts ───────────────────────────────────────────────────────────────
@bp.route("/alerts", methods=["GET"])
@_require_api_key
def alerts():
    """최근 알람 목록(가열살균 + 최종품질)을 반환합니다."""
    try:
        payload = _build_alert_payload()
        return jsonify(payload), 200
    except Exception as exc:
        return jsonify({"error": "Internal Server Error", "message": str(exc)}), 500


def _build_latest_sensor_payload():
    try:
        from haccp_dashboard.db_store import get_latest_sensor_event

        stored = get_latest_sensor_event()
        if stored is not None:
            if isinstance(stored, dict) and isinstance(stored.get("data"), list):
                return stored
            if isinstance(stored, list):
                return {"timestamp": datetime.now().isoformat(), "data": stored}
            if isinstance(stored, dict):
                return {"timestamp": datetime.now().isoformat(), "data": [stored]}
            return {"timestamp": datetime.now().isoformat(), "data": []}
    except Exception:
        pass

    from haccp_dashboard.lib.dashboard_demo import _load_process_dataframe

    df = _load_process_dataframe()
    now = datetime.now()
    payload_rows = []
    if not df.empty and "line_id" in df.columns:
        for line_id in sorted([value for value in df["line_id"].dropna().unique().tolist() if int(value) in (1, 2, 3)]):
            line_df = df[df["line_id"] == line_id].sort_values("datetime")
            if line_df.empty:
                continue
            eligible = line_df[line_df["datetime"] <= now]
            row = eligible.iloc[-1] if not eligible.empty else line_df.iloc[0]
            payload_rows.append(
                {
                    "timestamp": now.isoformat(),
                    "batch_id": int(row["batch_id"]),
                    "line_id": int(row["line_id"]) if row.get("line_id") is not None else None,
                    "line_run": int(row["line_run"]) if row.get("line_run") is not None and str(row.get("line_run")).strip() != "" else None,
                    "line_day": int(row["line_day"]) if row.get("line_day") is not None and str(row.get("line_day")).strip() != "" else None,
                    "state": str(row.get("state") or ""),
                    "temperature_celsius": round(float(row["T"]), 2),
                    "pH": round(float(row["pH"]), 3),
                    "flow_in_lpm": round(float(row["Q_in"]), 2),
                    "flow_out_lpm": round(float(row["Q_out"]), 2),
                    "T_z": round(float(row.get("T_z", 0.0) or 0.0), 3),
                    "pH_z": round(float(row.get("pH_z", 0.0) or 0.0), 3),
                    "Mu_z": round(float(row.get("Mu_z", 0.0) or 0.0), 3),
                    "Tau_z": round(float(row.get("Tau_z", 0.0) or 0.0), 3),
                    "contamination": str(row.get("contamination") or "no"),
                    "ccp_hold_temp_ok": bool(row.get("ccp_hold_temp_ok")),
                    "ccp_hold_time_ok": bool(row.get("ccp_hold_time_ok")),
                }
            )

    if not payload_rows and not df.empty:
        latest_batch = df["batch_id"].max()
        row = df[df["batch_id"] == latest_batch].iloc[-1]
        payload_rows.append(
            {
                "timestamp": now.isoformat(),
                "batch_id": int(row["batch_id"]),
                "line_id": int(row["line_id"]) if "line_id" in row and row.get("line_id") is not None else None,
                "line_run": int(row["line_run"]) if "line_run" in row and row.get("line_run") is not None else None,
                "line_day": int(row["line_day"]) if "line_day" in row and row.get("line_day") is not None else None,
                "state": str(row.get("state") or ""),
                "temperature_celsius": round(float(row["T"]), 2),
                "pH": round(float(row["pH"]), 3),
                "flow_in_lpm": round(float(row["Q_in"]), 2),
                "flow_out_lpm": round(float(row["Q_out"]), 2),
                "T_z": round(float(row.get("T_z", 0.0) or 0.0), 3),
                "pH_z": round(float(row.get("pH_z", 0.0) or 0.0), 3),
                "Mu_z": round(float(row.get("Mu_z", 0.0) or 0.0), 3),
                "Tau_z": round(float(row.get("Tau_z", 0.0) or 0.0), 3),
                "contamination": str(row.get("contamination") or "no"),
                "ccp_hold_temp_ok": bool(row.get("ccp_hold_temp_ok")),
                "ccp_hold_time_ok": bool(row.get("ccp_hold_time_ok")),
            }
        )

    return {"timestamp": now.isoformat(), "data": payload_rows}


def _build_alert_payload():
    """Build alert payload without importing Dash page modules.

    The dashboard expects `/api/alerts` to return a JSON object with `alerts`.
    Each alert should include at least: level, message, time.
    """
    sensor_payload = _build_latest_sensor_payload()
    rows = []
    if isinstance(sensor_payload, dict):
        rows = sensor_payload.get("data") or []

    now = datetime.now()
    alerts: list[dict] = []
    from haccp_dashboard.lib.heating_risk import HEATING_DANGER_Z_ABS, HEATING_WARNING_Z_ABS, extract_heating_z_values

    def _iso():
        return now.isoformat()

    def _add(level: str, message: str):
        alerts.append({"level": level, "message": message, "time": _iso()})

    for row in rows or []:
        if not isinstance(row, dict):
            continue

        batch_id = row.get("batch_id")
        line_id = row.get("line_id")
        prefix = f"Line {line_id} " if line_id else ""
        batch_text = f"{prefix}배치 {batch_id}" if batch_id is not None else f"{prefix}배치"

        if row.get("ccp_hold_temp_ok") is False:
            _add("위험", f"CCP 보온 온도 이탈: {batch_text} 즉시 확인/조치 필요")
        if row.get("ccp_hold_time_ok") is False:
            _add("위험", f"CCP 보온 시간 이탈: {batch_text} 즉시 확인/조치 필요")

        z_values = extract_heating_z_values(row)
        for metric_name, metric_z in z_values.items():
            if metric_z is None:
                continue
            abs_z = abs(float(metric_z))
            if abs_z >= HEATING_DANGER_Z_ABS:
                _add("위험", f"정상 범위 이탈(센서): {batch_text} {metric_name} z={float(metric_z):.2f}")
            elif abs_z >= HEATING_WARNING_Z_ABS:
                _add("경고", f"공정 안정도 변동(센서): {batch_text} {metric_name} z={float(metric_z):.2f}")

    return {
        "timestamp": now.isoformat(),
        "total": len(alerts),
        "alerts": alerts,
    }


@bp.route("/dashboard-stream", methods=["GET"])
def dashboard_stream():
    """Dash 내부 대시보드용 SSE 스트림"""

    if not _is_stream_authorized():
        return jsonify(
            {
                "error": "Unauthorized",
                "message": "dashboard-stream은 내부망 또는 유효한 stream_token에서만 접근할 수 있습니다.",
            }
        ), 401

    def generate():
        last_payload = None
        while True:
            try:
                payload = {
                    "sensor": _build_latest_sensor_payload(),
                    "alerts": _build_alert_payload(),
                    "runtime_status": {
                        "text": f"SSE 실시간 연결 정상: {request.base_url}",
                        "level": "success",
                        "source": "sse",
                        "last_error": "",
                        "sensor_ok": True,
                        "alerts_ok": True,
                        "sensor_error": "",
                        "alerts_error": "",
                    },
                }
            except Exception as exc:
                payload = {
                    "sensor": None,
                    "alerts": None,
                    "runtime_status": {
                        "text": f"SSE 스트림 오류: {exc}",
                        "level": "warning",
                        "source": "sse-error",
                        "last_error": str(exc),
                        "sensor_ok": False,
                        "alerts_ok": False,
                        "sensor_error": str(exc),
                        "alerts_error": str(exc),
                    },
                }

            serialized = json.dumps(payload, ensure_ascii=False)
            if serialized != last_payload:
                yield f"data: {serialized}\n\n"
                last_payload = serialized
            else:
                yield ": keepalive\n\n"

            time.sleep(2)

    response = Response(stream_with_context(generate()), mimetype="text/event-stream")
    response.headers["Cache-Control"] = "no-cache"
    response.headers["X-Accel-Buffering"] = "no"
    response.headers["Vary"] = "X-Forwarded-For"
    return _apply_cors_headers(response)


def _decode_base64_image_payload(raw: str) -> bytes:
    if not raw:
        return b""
    value = raw.strip()
    if value.startswith("data:") and "," in value:
        value = value.split(",", 1)[1]
    return base64.b64decode(value, validate=False)


@bp.route("/model-status", methods=["GET"])
def model_status():
    attempt = (request.args.get("attempt_load") or "").strip().lower() in {"1", "true", "yes", "on"}
    from haccp_dashboard.models import get_image_inference_status, get_inference_status

    return (
        jsonify(
            {
                "timestamp": datetime.now().isoformat(),
                "sensor_model": get_inference_status(attempt_load=attempt),
                "image_model": get_image_inference_status(attempt_load=attempt),
            }
        ),
        200,
    )


@bp.route("/infer/image", methods=["POST"])
@_require_api_key
def infer_image():
    """
    Image CNN inference endpoint for dashboard/flutter bridge.

    Accepts:
      - multipart/form-data: file field name `image` (or `file`)
      - application/json: {"image_base64": "<base64|data-url>", "topk": 3}
    """

    from haccp_dashboard.models import predict_image_class

    image_bytes = b""
    filename = None
    content_type = None

    if request.files:
        file = request.files.get("image") or request.files.get("file")
        if file:
            filename = file.filename
            content_type = file.mimetype
            image_bytes = file.read()

    if not image_bytes and request.is_json:
        payload = request.get_json(silent=True) or {}
        filename = payload.get("filename")
        content_type = payload.get("content_type")
        image_bytes = _decode_base64_image_payload(str(payload.get("image_base64", "") or ""))

    if not image_bytes:
        return jsonify({"error": "Bad Request", "message": "No image provided. Use multipart file or JSON image_base64."}), 400

    topk = 3
    try:
        if request.is_json:
            topk = int((request.get_json(silent=True) or {}).get("topk", 3))
        else:
            topk = int(request.form.get("topk", 3)) if request.form else 3
    except Exception:
        topk = 3

    prediction = predict_image_class(image_bytes=image_bytes, topk=topk)
    return (
        jsonify(
            {
                "timestamp": datetime.now().isoformat(),
                "filename": filename,
                "content_type": content_type,
                "prediction": prediction,
            }
        ),
        200,
    )


def _emit_socketio(event_name: str, payload: dict):
    socketio = current_app.extensions.get("socketio") if current_app else None
    if socketio is None:
        return
    try:
        socketio.emit(event_name, payload)
    except Exception:
        return


@bp.route("/db-health", methods=["GET"])
def db_health():
    try:
        from haccp_dashboard.db_store import db_health as _db_health

        return jsonify({"timestamp": datetime.now().isoformat(), **_db_health()}), 200
    except Exception as exc:
        return jsonify({"error": "Internal Server Error", "message": str(exc)}), 500


@bp.route("/ingest/sensor", methods=["POST"])
@_require_api_key
def ingest_sensor():
    payload = request.get_json(silent=True) or {}
    try:
        from haccp_dashboard.db_store import insert_sensor_event

        meta = insert_sensor_event(payload=payload, source=str(payload.get("source") or "api"))
        stored_payload = {"timestamp": meta["created_at"], **payload}
        _emit_socketio("sensor_event", stored_payload)
        return jsonify({"timestamp": datetime.now().isoformat(), **meta}), 201
    except Exception as exc:
        return jsonify({"error": "Bad Request", "message": str(exc)}), 400


@bp.route("/ingest/image", methods=["POST"])
@_require_api_key
def ingest_image():
    file = request.files.get("image") or request.files.get("file")
    if not file:
        return jsonify({"error": "Bad Request", "message": "No image file provided (field `image` or `file`)."}), 400

    try:
        from haccp_dashboard.db_store import insert_image_event

        image_bytes = file.read()
        record = insert_image_event(
            image_bytes=image_bytes,
            filename=file.filename,
            content_type=file.mimetype,
            source=request.form.get("source") or "api",
            meta={"note": request.form.get("note") or ""},
        )
        safe_record = {k: v for k, v in record.items() if k != "file_path"}
        _emit_socketio("image_event", safe_record)
        return jsonify({"timestamp": datetime.now().isoformat(), **safe_record}), 201
    except Exception as exc:
        return jsonify({"error": "Bad Request", "message": str(exc)}), 400


@bp.route("/images/<int:image_id>/file", methods=["GET"])
@_require_api_key
def download_image_file(image_id: int):
    try:
        from haccp_dashboard.db_store import get_image_event

        record = get_image_event(int(image_id))
        if record is None:
            return jsonify({"error": "Not Found", "message": "Image not found"}), 404

        return send_file(
            record["file_path"],
            mimetype=record.get("content_type") or "application/octet-stream",
            as_attachment=False,
            download_name=record.get("filename") or f"image_{image_id}",
        )
    except Exception as exc:
        return jsonify({"error": "Internal Server Error", "message": str(exc)}), 500


@bp.route("/reports", methods=["GET", "POST"])
@_require_api_key
def reports():
    if request.method == "POST":
        payload = request.get_json(silent=True) or {}
        try:
            from haccp_dashboard.db_store import insert_report

            meta = insert_report(
                title=str(payload.get("title") or ""),
                body=str(payload.get("body") or ""),
                source=str(payload.get("source") or "api"),
                meta={k: v for k, v in payload.items() if k not in {"title", "body"}},
            )
            _emit_socketio(
                "report_event",
                {"id": meta["id"], "created_at": meta["created_at"], "title": payload.get("title")},
            )
            return jsonify({"timestamp": datetime.now().isoformat(), **meta}), 201
        except Exception as exc:
            return jsonify({"error": "Bad Request", "message": str(exc)}), 400

    try:
        from haccp_dashboard.db_store import list_reports

        limit = int(request.args.get("limit", "20"))
        return jsonify({"timestamp": datetime.now().isoformat(), "reports": list_reports(limit=limit)}), 200
    except Exception as exc:
        return jsonify({"error": "Internal Server Error", "message": str(exc)}), 500
