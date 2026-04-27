"""Central state manager for HACCP dashboard.

모든 페이지는 get_per_line_states()를 통해 라인별 현재 배치 상태를 가져오고,
get_summary_kpis()를 통해 전체 KPI 집계를 가져옵니다.
이렇게 함으로써 메인/가열 페이지가 서로 다른 Batch를 보여주는 것을 방지합니다.
"""
from __future__ import annotations

from functools import lru_cache


def get_per_line_states() -> dict[int, dict]:
    """현재 시점 기준 라인별 배치 상태를 계산합니다.

    Returns
    -------
    dict
        {line_id: {line_id, batch_id, batch_name, stage, stage_label,
                   T, pH, ccp_ok, similarity_scores, top_name, top_score,
                   sensor_status, ai_judgement, action_message, stability_score, ...}}
    """
    try:
        from haccp_dashboard.lib.main_helpers import (
            resolve_current_process_snapshot,
            resolve_similarity_contamination_view,
        )
        from haccp_dashboard.lib.dashboard_demo import get_batch_summary_frame
        from haccp_dashboard.utils.status_logic import classify_sensor_status

        snapshot = resolve_current_process_snapshot()
        summary_frame = get_batch_summary_frame()

        result = {}
        for line_id, snap in snapshot.items():
            batch_id = snap.get("batch_id")
            stage = snap.get("state", "Hold")
            batch_name = f"BATCH-{int(batch_id):03d}" if batch_id else "-"

            # 배치 요약 행 찾기
            summary_row = None
            if batch_id is not None and not summary_frame.empty:
                matches = summary_frame[summary_frame["batch_id"] == int(batch_id)]
                if not matches.empty:
                    summary_row = matches.iloc[0]

            if summary_row is not None:
                view = resolve_similarity_contamination_view(summary_row, stage=None)
                sensor_status = view.get("status", "정상")
                top_name = view.get("top_name", "-")
                top_score = float(view.get("top_score", 0.0))
                similarity_scores = view.get("similarity_scores", {})
                stability = float(summary_row.get("stability_score", 100.0))
                ccp_ok = bool(summary_row.get("hold_time_ok", True)) and bool(summary_row.get("hold_temp_ok", True))
                peak_temp = float(summary_row.get("peak_temp", 0.0))
                final_temp = float(summary_row.get("final_temp", 0.0))
                final_ph = float(summary_row.get("final_ph", 6.7))
                hold_minutes = float(summary_row.get("hold_minutes", 0.0))
                risk_level = str(summary_row.get("risk_level", "정상"))
                inferred_stage = view.get("stage", stage)
            else:
                # 스냅샷만으로 판정
                ccp_ok = bool(snap.get("ccp_hold_time_ok", 1)) and bool(snap.get("ccp_hold_temp_ok", 1))
                from haccp_dashboard.lib.main_helpers import _infer_stage_from_state
                inferred_stage = _infer_stage_from_state(stage)
                top_name, top_score, similarity_scores = "-", 0.0, {}
                stability = 100.0
                sensor_status = classify_sensor_status(0.0, 100.0, ccp_ok)
                peak_temp = float(snap.get("T", 0.0))
                final_temp = float(snap.get("T", 0.0))
                final_ph = float(snap.get("pH", 6.7))
                hold_minutes = 0.0
                risk_level = "정상"

            # AI 판정 문구 (현장 담당자 친화적 표현)
            if sensor_status == "위험":
                ai_judgement = f"{top_name} 오염 가능성 감지(유사도 {top_score:.2f}) — 즉시 점검이 필요합니다."
                action_message = "즉시 공정을 멈추고 해당 배치 출하를 보류하세요. 원인 점검 필요."
            elif sensor_status == "경고":
                ai_judgement = f"{top_name} 유사도 {top_score:.2f} — 물성 이상 신호가 확인됩니다."
                action_message = "물성 지표 이상징후 감지 — 오염 가능성 확인 필요."
            else:
                ai_judgement = "공정 운영이 정상 범위입니다."
                action_message = "운영 상태 양호 — 정기 점검 일정을 유지하세요."

            from haccp_dashboard.lib.process_spec import PROCESS_STAGE_LABELS
            stage_label = PROCESS_STAGE_LABELS.get(snap.get("state", ""), snap.get("state", ""))

            result[int(line_id)] = {
                "line_id": int(line_id),
                "batch_id": batch_id,
                "batch_name": batch_name,
                "stage": inferred_stage,          # HeatUp / Hold / Cool
                "stage_raw": snap.get("state", ""),  # Receiving / Heat / ... / Release
                "stage_label": stage_label,
                "T": float(snap.get("T", 0.0)),
                "pH": float(snap.get("pH", 6.7)),
                "T_z": float(snap.get("T_z", 0.0)),
                "pH_z": float(snap.get("pH_z", 0.0)),
                "Mu_z": float(snap.get("Mu_z", 0.0)),
                "Tau_z": float(snap.get("Tau_z", 0.0)),
                "ccp_ok": ccp_ok,
                "peak_temp": peak_temp,
                "final_temp": final_temp,
                "final_ph": final_ph,
                "hold_minutes": hold_minutes,
                "stability_score": stability,
                "similarity_scores": similarity_scores,
                "top_name": top_name,
                "top_score": top_score,
                "sensor_status": sensor_status,
                "ai_judgement": ai_judgement,
                "action_message": action_message,
                "risk_level": risk_level,
            }
        return result

    except Exception:
        # 폴백
        return {
            1: _fallback_line_state(1),
            2: _fallback_line_state(2),
            3: _fallback_line_state(3),
        }


def _fallback_line_state(line_id: int) -> dict:
    return {
        "line_id": line_id,
        "batch_id": 20 + line_id,
        "batch_name": f"BATCH-0{20 + line_id:02d}",
        "stage": "Hold",
        "stage_raw": "Hold",
        "stage_label": "보온",
        "T": 72.0,
        "pH": 6.7,
        "T_z": 0.5,
        "pH_z": 0.3,
        "Mu_z": 0.2,
        "Tau_z": 0.4,
        "ccp_ok": True,
        "peak_temp": 72.0,
        "final_temp": 6.5,
        "final_ph": 6.7,
        "hold_minutes": 15.0,
        "stability_score": 82.0,
        "similarity_scores": {"NaOH": 0.22, "HNO3": 0.18, "E.coli": 0.42, "Salmonella": 0.38, "Listeria": 0.25},
        "top_name": "E.coli",
        "top_score": 0.42,
        "sensor_status": "정상",
        "ai_judgement": "정상 범위 내 운영 중입니다.",
        "action_message": "정기 점검 일정을 유지하세요.",
        "risk_level": "정상",
    }


def get_summary_kpis() -> dict:
    """전체 공정 KPI 집계를 반환합니다.

    Returns
    -------
    dict
        active_lines, ccp_deviation_count, warning_batch_count,
        danger_batch_count, unresolved_alarm_count, shipment_risk_count
    """
    try:
        from haccp_dashboard.lib.dashboard_demo import get_batch_summary_frame, _filter_summary
        from haccp_dashboard.lib.main_helpers import get_dashboard_current_lot_index, LINE_COUNT

        summary = _filter_summary("today")
        if summary.empty:
            summary = get_batch_summary_frame().head(LINE_COUNT * get_dashboard_current_lot_index())

        ccp_dev = int(
            (~(summary["hold_time_ok"].astype(bool) & summary["hold_temp_ok"].astype(bool))).sum()
        ) if not summary.empty else 0

        danger_count = int((summary["risk_level"] == "위험").sum()) if not summary.empty else 0
        warning_count = int((summary["risk_level"] == "경고").sum()) if not summary.empty else 0

        # 출하 영향 = 위험 + CCP 이탈
        shipment_risk = int(
            (summary["risk_level"].isin(["위험"]) | ~(summary["hold_time_ok"].astype(bool) & summary["hold_temp_ok"].astype(bool))).sum()
        ) if not summary.empty else 0

        # 미조치 알람: 위험 배치 수 (실제 DB 연동 시 상태 필터 추가)
        unresolved_alarms = danger_count

        return {
            "active_lines": int(LINE_COUNT),
            "ccp_deviation_count": ccp_dev,
            "warning_batch_count": warning_count,
            "danger_batch_count": danger_count,
            "unresolved_alarm_count": unresolved_alarms,
            "shipment_risk_count": shipment_risk,
            "total_batches": len(summary),
        }
    except Exception:
        return {
            "active_lines": 3,
            "ccp_deviation_count": 2,
            "warning_batch_count": 3,
            "danger_batch_count": 1,
            "unresolved_alarm_count": 1,
            "shipment_risk_count": 2,
            "total_batches": 0,
        }
