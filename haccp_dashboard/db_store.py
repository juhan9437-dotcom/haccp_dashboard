from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


_BASE_DIR = Path(__file__).resolve().parent
_DATA_DIR = Path(os.getenv("HACCP_DATA_DIR", str(_BASE_DIR / "data")))
_DB_PATH = Path(os.getenv("HACCP_DB_PATH", str(_DATA_DIR / "haccp.sqlite3")))
_UPLOAD_DIR = Path(os.getenv("HACCP_UPLOAD_DIR", str(_DATA_DIR / "uploads")))


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _ensure_dirs():
    _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    _UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


@contextmanager
def _connect():
    _ensure_dirs()
    conn = sqlite3.connect(str(_DB_PATH), timeout=30)
    conn.row_factory = sqlite3.Row
    try:
        _init_schema(conn)
        yield conn
        conn.commit()
    finally:
        conn.close()


def _init_schema(conn: sqlite3.Connection):
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    conn.execute("PRAGMA busy_timeout=30000;")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS sensor_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT NOT NULL,
            source TEXT,
            payload_json TEXT NOT NULL
        );
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS image_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT NOT NULL,
            source TEXT,
            filename TEXT,
            content_type TEXT,
            sha256 TEXT NOT NULL,
            file_path TEXT NOT NULL,
            meta_json TEXT
        );
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS reports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT NOT NULL,
            source TEXT,
            title TEXT,
            body TEXT,
            meta_json TEXT
        );
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS alert_events (
            id TEXT PRIMARY KEY,
            created_at TEXT NOT NULL,
            source TEXT,
            level TEXT,
            message TEXT,
            event_type TEXT,
            line_id INTEGER,
            batch_id INTEGER,
            stage TEXT,
            status TEXT,
            meta_json TEXT
        );
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_sensor_events_created_at ON sensor_events(created_at);")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_image_events_created_at ON image_events(created_at);")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_reports_created_at ON reports(created_at);")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_alert_events_created_at ON alert_events(created_at);")


def db_health() -> dict[str, Any]:
    with _connect() as conn:
        sensor_count = conn.execute("SELECT COUNT(1) AS n FROM sensor_events;").fetchone()["n"]
        image_count = conn.execute("SELECT COUNT(1) AS n FROM image_events;").fetchone()["n"]
        report_count = conn.execute("SELECT COUNT(1) AS n FROM reports;").fetchone()["n"]
        alert_count = conn.execute("SELECT COUNT(1) AS n FROM alert_events;").fetchone()["n"]
    return {
        "db_path": str(_DB_PATH),
        "upload_dir": str(_UPLOAD_DIR),
        "sensor_events": int(sensor_count),
        "image_events": int(image_count),
        "reports": int(report_count),
        "alert_events": int(alert_count),
    }


def insert_alert_event(payload: dict[str, Any], source: str | None = None) -> dict[str, Any]:
    if not isinstance(payload, dict) or not payload:
        raise ValueError("alert payload must be a non-empty dict")
    alert_id = str(payload.get("id") or "").strip()
    if not alert_id:
        raise ValueError("alert payload must include a stable 'id'")

    created_at = str(payload.get("occurred_at") or payload.get("created_at") or payload.get("time_iso") or _utcnow_iso())
    level = str(payload.get("level") or payload.get("severity") or "")
    message = str(payload.get("message") or "")
    event_type = str(payload.get("event_type") or payload.get("type") or payload.get("source") or "")
    status = str(payload.get("status") or payload.get("action_status") or "")

    line_id = payload.get("line_id")
    batch_id = payload.get("batch_id")
    stage = payload.get("stage") or payload.get("state") or payload.get("process_stage")

    try:
        line_id_int = int(line_id) if line_id is not None and str(line_id).strip() != "" else None
    except Exception:
        line_id_int = None
    try:
        batch_id_int = int(batch_id) if batch_id is not None and str(batch_id).strip() != "" else None
    except Exception:
        batch_id_int = None

    meta = dict(payload.get("meta") or {})
    for key in ("time_label", "source", "extra"):
        if key in payload and key not in meta:
            meta[key] = payload.get(key)

    with _connect() as conn:
        conn.execute(
            """
            INSERT OR IGNORE INTO alert_events(
                id, created_at, source, level, message, event_type, line_id, batch_id, stage, status, meta_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
            """,
            (
                alert_id,
                created_at,
                source,
                level,
                message,
                event_type,
                line_id_int,
                batch_id_int,
                str(stage) if stage is not None else None,
                status,
                json.dumps(meta, ensure_ascii=False),
            ),
        )
    return {"id": alert_id, "created_at": created_at}


def list_alert_events(limit: int = 200) -> list[dict[str, Any]]:
    limit = max(1, min(int(limit), 2000))
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM alert_events ORDER BY created_at DESC LIMIT ?;",
            (limit,),
        ).fetchall()
    result: list[dict[str, Any]] = []
    for row in rows:
        meta = json.loads(row["meta_json"]) if row["meta_json"] else {}
        result.append(
            {
                "id": str(row["id"]),
                "occurred_at": str(row["created_at"]),
                "source": row["source"],
                "level": row["level"],
                "message": row["message"],
                "event_type": row["event_type"],
                "line_id": row["line_id"],
                "batch_id": row["batch_id"],
                "stage": row["stage"],
                "status": row["status"],
                "meta": meta,
            }
        )
    return result


def insert_sensor_event(payload: dict[str, Any], source: str | None = None) -> dict[str, Any]:
    if not isinstance(payload, dict) or not payload:
        raise ValueError("sensor payload must be a non-empty JSON object")

    created_at = _utcnow_iso()
    with _connect() as conn:
        cursor = conn.execute(
            "INSERT INTO sensor_events(created_at, source, payload_json) VALUES(?, ?, ?);",
            (created_at, source, json.dumps(payload, ensure_ascii=False)),
        )
        event_id = int(cursor.lastrowid)
    return {"id": event_id, "created_at": created_at}


def _normalize_sensor_payload(created_at: str, raw: dict[str, Any]) -> dict[str, Any]:
    # Preserve existing API shape when possible.
    payload = dict(raw)
    payload.setdefault("timestamp", created_at)

    if "temperature_celsius" not in payload and "T" in payload:
        try:
            payload["temperature_celsius"] = float(payload["T"])
        except Exception:
            pass
    if "flow_in_lpm" not in payload and "Q_in" in payload:
        try:
            payload["flow_in_lpm"] = float(payload["Q_in"])
        except Exception:
            pass
    if "flow_out_lpm" not in payload and "Q_out" in payload:
        try:
            payload["flow_out_lpm"] = float(payload["Q_out"])
        except Exception:
            pass
    return payload


def get_latest_sensor_event() -> dict[str, Any] | None:
    with _connect() as conn:
        row = conn.execute(
            "SELECT id, created_at, payload_json FROM sensor_events ORDER BY id DESC LIMIT 1;"
        ).fetchone()
        if not row:
            return None
        created_at = str(row["created_at"])
        payload = json.loads(row["payload_json"])
    return _normalize_sensor_payload(created_at, payload)


def _safe_filename(name: str) -> str:
    base = (name or "upload").strip().replace("\\", "_").replace("/", "_")
    base = re.sub(r"[^0-9A-Za-z._-]+", "_", base)
    return base[:120] or "upload"


def insert_image_event(
    image_bytes: bytes,
    filename: str | None = None,
    content_type: str | None = None,
    source: str | None = None,
    meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if not image_bytes:
        raise ValueError("empty image payload")

    created_at = _utcnow_iso()
    sha256 = hashlib.sha256(image_bytes).hexdigest()
    safe_name = _safe_filename(filename or "image")
    ext = Path(safe_name).suffix or ".bin"
    file_path = _UPLOAD_DIR / f"{created_at.replace(':', '').replace('+', '_')}_{sha256[:12]}{ext}"
    file_path.write_bytes(image_bytes)

    with _connect() as conn:
        cursor = conn.execute(
            """
            INSERT INTO image_events(created_at, source, filename, content_type, sha256, file_path, meta_json)
            VALUES(?, ?, ?, ?, ?, ?, ?);
            """,
            (
                created_at,
                source,
                filename,
                content_type,
                sha256,
                str(file_path),
                json.dumps(meta or {}, ensure_ascii=False),
            ),
        )
        event_id = int(cursor.lastrowid)

    return {
        "id": event_id,
        "created_at": created_at,
        "filename": filename,
        "content_type": content_type,
        "sha256": sha256,
        "file_path": str(file_path),
    }


def get_image_event(event_id: int) -> dict[str, Any] | None:
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM image_events WHERE id = ?;",
            (int(event_id),),
        ).fetchone()
        if not row:
            return None
    meta = json.loads(row["meta_json"]) if row["meta_json"] else {}
    return {
        "id": int(row["id"]),
        "created_at": str(row["created_at"]),
        "source": row["source"],
        "filename": row["filename"],
        "content_type": row["content_type"],
        "sha256": row["sha256"],
        "file_path": row["file_path"],
        "meta": meta,
    }


def insert_report(title: str | None, body: str | None, source: str | None = None, meta: dict[str, Any] | None = None) -> dict[str, Any]:
    created_at = _utcnow_iso()
    with _connect() as conn:
        cursor = conn.execute(
            "INSERT INTO reports(created_at, source, title, body, meta_json) VALUES(?, ?, ?, ?, ?);",
            (created_at, source, title, body, json.dumps(meta or {}, ensure_ascii=False)),
        )
        report_id = int(cursor.lastrowid)
    return {"id": report_id, "created_at": created_at}


def list_reports(limit: int = 20) -> list[dict[str, Any]]:
    limit = max(1, min(int(limit), 200))
    with _connect() as conn:
        rows = conn.execute(
            "SELECT id, created_at, source, title, body, meta_json FROM reports ORDER BY id DESC LIMIT ?;",
            (limit,),
        ).fetchall()
    result = []
    for row in rows:
        result.append(
            {
                "id": int(row["id"]),
                "created_at": str(row["created_at"]),
                "source": row["source"],
                "title": row["title"],
                "body": row["body"],
                "meta": json.loads(row["meta_json"]) if row["meta_json"] else {},
            }
        )
    return result
