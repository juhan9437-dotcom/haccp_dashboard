from __future__ import annotations

from hashlib import md5


def _stable_id(*parts: str) -> str:
    raw = "|".join(str(p) for p in parts if p is not None)
    return md5(raw.encode("utf-8")).hexdigest()[:16]


def seed_demo_alert_log_if_empty(limit_days: int = 5) -> None:
    """
    Seed a realistic cumulative alert log into sqlite for demo/offline runs.

    - Uses the shared process spec (3 lines / 5 days / 150 batches) time axis.
    - Ensures normal is the majority; warnings and critical events are rare.
    - Inserts are idempotent via INSERT OR IGNORE.
    """
    try:
        from haccp_dashboard.db_store import insert_alert_event, list_alert_events
    except Exception:
        return

    try:
        # If we already have a meaningful amount of history, do nothing.
        if len(list_alert_events(limit=50)) >= 30:
            return
    except Exception:
        return

    import pandas as pd
    from haccp_dashboard.lib import dashboard_demo as demo

    batch_summary = demo.get_batch_summary_frame()
    if batch_summary is None or getattr(batch_summary, "empty", True):
        return

    now = pd.Timestamp.now()
    summary = batch_summary.copy()
    summary["end_time"] = pd.to_datetime(summary["end_time"], errors="coerce")
    summary = summary.dropna(subset=["end_time"]).sort_values(["end_time", "batch_id"], ascending=[True, True])

    # Limit to recent days (default 5) to keep logs readable.
    if "date" in summary.columns:
        summary["date"] = pd.to_datetime(summary["date"], errors="coerce").dt.date
        if summary["date"].notna().any():
            latest = summary["date"].max()
            min_date = latest - pd.Timedelta(days=max(int(limit_days) - 1, 0))
            summary = summary[summary["date"] >= min_date]

    # Completed batches only.
    completed = summary[summary["end_time"] <= now]

    for row in completed.itertuples(index=False):
        batch_id = int(getattr(row, "batch_id"))
        line_id = getattr(row, "line_id", None)
        stage = getattr(row, "last_state", None)
        occurred_at = pd.Timestamp(getattr(row, "end_time")).replace(microsecond=0).isoformat()

        risk_level = str(getattr(row, "risk_level", "정상"))
        hold_temp_ok = bool(getattr(row, "hold_temp_ok", True))
        hold_time_ok = bool(getattr(row, "hold_time_ok", True))

        # Critical: CCP deviation (rare) or sustained sensor out-of-range.
        if (not hold_temp_ok) or (not hold_time_ok):
            insert_alert_event(
                {
                    "id": f"demo-{_stable_id('ccp', str(batch_id), occurred_at)}",
                    "level": "위험",
                    "message": f"CCP 이탈: BATCH-{batch_id:03d} (살균/보온 조건 확인 필요)",
                    "occurred_at": occurred_at,
                    "event_type": "ccp_deviation",
                    "line_id": line_id,
                    "batch_id": batch_id,
                    "stage": stage,
                    "status": "미해결",
                },
                source="demo-seed",
            )
            continue

        if risk_level == "위험":
            insert_alert_event(
                {
                    "id": f"demo-{_stable_id('sensor_danger', str(batch_id), occurred_at)}",
                    "level": "위험",
                    "message": f"센서 이상(위험): BATCH-{batch_id:03d} 공정 안정도 이탈",
                    "occurred_at": occurred_at,
                    "event_type": "sensor_out_of_range",
                    "line_id": line_id,
                    "batch_id": batch_id,
                    "stage": stage,
                    "status": "미해결",
                },
                source="demo-seed",
            )
        elif risk_level == "경고":
            # Only seed a subset of warnings to avoid noisy logs.
            choose = int(_stable_id("warn_pick", str(batch_id))[:2], 16) % 3 == 0
            if choose:
                insert_alert_event(
                    {
                        "id": f"demo-{_stable_id('sensor_warn', str(batch_id), occurred_at)}",
                        "level": "경고",
                        "message": f"센서 이상(경고): BATCH-{batch_id:03d} 변동성 증가(모니터링 필요)",
                        "occurred_at": occurred_at,
                        "event_type": "sensor_instability",
                        "line_id": line_id,
                        "batch_id": batch_id,
                        "stage": stage,
                        "status": "처리중",
                    },
                    source="demo-seed",
                )

    # Seed final-product decisions (warning/critical only).
    final_summary = demo.get_final_product_batch_summary_frame()
    if final_summary is None or getattr(final_summary, "empty", True):
        return

    merged = final_summary.merge(
        summary[["batch_id", "end_time", "line_id"]],
        on="batch_id",
        how="left",
        suffixes=("", "_proc"),
    )
    merged["end_time"] = pd.to_datetime(merged["end_time"], errors="coerce")
    merged = merged.dropna(subset=["end_time"])

    for row in merged.itertuples(index=False):
        level = str(getattr(row, "risk_level", "정상"))
        if level not in {"경고", "위험"}:
            continue
        batch_id = int(getattr(row, "batch_id"))
        line_id = getattr(row, "line_id", None)
        occurred_at = pd.Timestamp(getattr(row, "end_time")).replace(microsecond=0).isoformat()
        disposition = str(getattr(row, "disposition", getattr(row, "status", "")) or "")
        event_type = "final_hold" if level == "경고" else "final_reject"

        insert_alert_event(
            {
                "id": f"demo-{_stable_id(event_type, str(batch_id), occurred_at)}",
                "level": level,
                "message": f"최종제품공정 {disposition}: BATCH-{batch_id:03d}",
                "occurred_at": occurred_at,
                "event_type": event_type,
                "line_id": line_id,
                "batch_id": batch_id,
                "stage": "Inspect",
                "status": "처리중" if level == "경고" else "미해결",
            },
            source="demo-seed",
        )
