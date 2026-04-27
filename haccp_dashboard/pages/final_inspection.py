from __future__ import annotations

import base64
import io

import dash
import json

import dash
from dash import ALL, Input, Output, State, callback, dcc, html
from haccp_dashboard.components.status_badges import (
    kpi_card as _kpi_card,
    kpi_row as _kpi_row,
)
from haccp_dashboard.models import (
    get_image_inference_status,
    get_inference_status,
    predict_contamination,
    predict_image_class,
)


dash.register_page(__name__, path="/final-inspection")

DEFAULT_PERIOD = "week"

PREDICTION_META = {
    "no": {
        "title": "정상 가능성 우세",
        "badge": "정상",
        "tone": "safe",
        "light": "green",
        "description": "1차 모델 기준 오염 신호가 기준선 아래입니다.",
    },
    "bio": {
        "title": "생물학 오염 의심",
        "badge": "생물학",
        "tone": "danger",
        "light": "red",
        "description": "2차 모델이 생물학적 오염 패턴에 더 가깝다고 판독했습니다.",
    },
    "chem": {
        "title": "화학 혼입 의심",
        "badge": "화학",
        "tone": "warning",
        "light": "amber",
        "description": "2차 모델이 화학적 혼입 패턴에 더 가깝다고 판독했습니다.",
    },
}


def _product_card(title, value, unit, caption, color="#1f2937", is_main=False):
    """최종검사 제품 카드 (전 페이지 공통 KPI 컴포넌트 사용)."""
    display_value = f"{value} {unit}".strip() if unit else str(value)
    return _kpi_card(title, display_value, caption)


def _metric_stat_card(title, value, caption):
    return html.Div(
        [
            html.Div(title, className="inspection-upload-stat-label"),
            html.Div(value, className="inspection-upload-stat-value"),
            html.Div(caption, className="inspection-upload-stat-caption"),
        ],
        className="inspection-upload-stat-card",
    )


def _prediction_badge(label, tone):
    class_name = "inspection-prediction-badge"
    if tone:
        class_name = f"{class_name} {class_name}--{tone}"
    return html.Span(label, className=class_name)


def _build_upload_status_panel(upload_data=None, error_message=None):
    inference_status = get_inference_status()
    status_title = "모델 자산 준비 완료" if inference_status["assets_present"] else "모델 자산 준비 필요"
    status_tone = "safe" if inference_status["assets_present"] else "warning"
    file_badge = _prediction_badge("CSV 대기", "neutral")
    file_summary = "업로드된 파일이 없습니다."
    rows_value = "-"
    feature_value = "-"
    column_preview = "CSV 업로드 후 센서 컬럼 구성을 확인합니다."

    if upload_data:
        file_badge = _prediction_badge("업로드 완료", "safe")
        file_summary = f"{upload_data['filename']}"
        rows_value = f"{upload_data['rows']:,}"
        feature_value = str(max(len(upload_data["columns"]) - 4, 0))
        preview_columns = upload_data["columns"][:6]
        column_preview = ", ".join(preview_columns) if preview_columns else "컬럼 정보 없음"

    if error_message:
        file_badge = _prediction_badge("업로드 실패", "danger")
        file_summary = error_message

    return html.Div(
        [
            html.Div(
                [
                    html.Div(
                        [
                            html.Div("CSV 기반 오염 판독", className="inspection-panel-title"),
                            html.Div(
                                "모델 파일, scaler, inference 파이프라인을 직접 연결한 업로드 추론 존입니다.",
                                className="inspection-panel-subtitle",
                            ),
                        ]
                    ),
                    _prediction_badge(status_title, status_tone),
                ],
                className="inspection-panel-header",
            ),
            html.Div(
                [
                    html.Div(
                        [
                            html.Div("입력 파일", className="inspection-mini-label"),
                            file_badge,
                        ],
                        className="inspection-inline-label-row",
                    ),
                    html.Div(file_summary, className="inspection-upload-file-name"),
                    html.Div(column_preview, className="inspection-upload-file-meta"),
                ],
                className="inspection-upload-file-card",
            ),
            html.Div(
                [
                    _metric_stat_card("샘플 행 수", rows_value, "업로드 CSV 기준"),
                    _metric_stat_card("유효 피처", feature_value, "식별 컬럼 제외 예상값"),
                    _metric_stat_card("모델 경로", "models/", "서버 시작 시 1회 로드"),
                ],
                className="inspection-upload-stat-grid",
            ),
            html.Div(
                [
                    html.Div(
                        [
                            html.Div("권장 CSV 구성", className="inspection-mini-label"),
                            html.Div(
                                "19피처 입력 CSV는 그대로 사용 가능하고, 원본 공정 CSV는 timestamp 기반 시간 특성을 자동 생성해 19피처로 변환합니다.",
                                className="inspection-note-text",
                            ),
                        ]
                    ),
                    html.Div(
                        inference_status["error"] if inference_status["error"] else "현재 모델 자산과 로딩 경로가 확인되었습니다.",
                        className="inspection-note-text",
                    ),
                ],
                className="inspection-note-box",
            ),
        ],
        className="inspection-upload-card",
    )


def _build_image_upload_status_panel(upload_data=None, error_message=None):
    inference_status = get_image_inference_status()
    status_title = "CNN 자산 준비 완료" if inference_status["assets_present"] else "CNN 자산 준비 필요"
    status_tone = "safe" if inference_status["assets_present"] else "warning"
    file_badge = _prediction_badge("이미지 대기", "neutral")
    file_summary = "업로드된 이미지가 없습니다."

    if upload_data:
        file_badge = _prediction_badge("업로드 완료", "safe")
        file_summary = f"{upload_data['filename']}"

    if error_message:
        file_badge = _prediction_badge("업로드 실패", "danger")
        file_summary = error_message

    return html.Div(
        [
            html.Div(
                [
                    html.Div(
                        [
                            html.Div("이미지 기반 CNN 판독", className="inspection-panel-title"),
                            html.Div(
                                "mobilenetv2 TorchScript(.pt) 모델로 이미지를 분류합니다.",
                                className="inspection-panel-subtitle",
                            ),
                        ]
                    ),
                    _prediction_badge(status_title, status_tone),
                ],
                className="inspection-panel-header",
            ),
            html.Div(
                [
                    html.Div(
                        [
                            html.Div("입력 파일", className="inspection-mini-label"),
                            file_badge,
                        ],
                        className="inspection-inline-label-row",
                    ),
                    html.Div(file_summary, className="inspection-upload-file-name"),
                    html.Div(
                        inference_status["error"] if inference_status["error"] else "모델 자산 경로가 확인되었습니다.",
                        className="inspection-upload-file-meta",
                    ),
                ],
                className="inspection-upload-file-card",
            ),
        ],
        className="inspection-upload-card",
    )


def _build_inference_idle_panel():
    return html.Div(
        [
            html.Div("AI 오염 유사도 분석", className="inspection-panel-title"),
            html.Div(
                "CSV를 업로드하고 추론 실행을 누르면 오염 유형, 유사도 지표, AI 요약 브리핑을 표시합니다.",
                className="inspection-panel-subtitle",
            ),
            html.Div(
                [
                    html.Div(className="inspection-warning-light inspection-warning-light--idle"),
                    html.Div(
                        [
                            html.Div("대기 중", className="inspection-result-title"),
                            html.Div("추론 전에는 결과 카드가 표시되지 않습니다.", className="inspection-result-copy"),
                        ]
                    ),
                ],
                className="inspection-result-hero",
            ),
        ],
        className="inspection-ai-report-card",
    )


def _build_image_inference_idle_panel():
    return html.Div(
        [
            html.Div("이미지 CNN 판독", className="inspection-panel-title"),
            html.Div(
                "이미지를 업로드하고 판독 실행을 누르면 분류 결과를 표시합니다.",
                className="inspection-panel-subtitle",
            ),
            html.Div(
                [
                    html.Div(className="inspection-warning-light inspection-warning-light--idle"),
                    html.Div(
                        [
                            html.Div("대기 중", className="inspection-result-title"),
                            html.Div("판독 전에는 결과 카드가 표시되지 않습니다.", className="inspection-result-copy"),
                        ]
                    ),
                ],
                className="inspection-result-hero",
            ),
        ],
        className="inspection-ai-report-card",
    )


def _build_cnn_ai_summary(result: dict) -> dict:
    """CNN 분류 결과를 HACCP 관점에서 해석하는 요약 페이로드를 반환합니다."""
    label = result.get("label", "unknown")
    prob = float(result.get("prob", 0.0))
    topk = result.get("topk", []) or []

    label_lower = label.lower().replace(" ", "_").replace("-", "_")
    topk_str = ", ".join(
        f"{item.get('label','?')}({float(item.get('prob', 0.0)) * 100:.1f}%)"
        for item in topk[:3]
    )

    if "pure" in label_lower or "순수" in label_lower:
        risk_line = f"CNN 모델이 '{label}'로 분류했습니다 (신뢰도 {prob * 100:.1f}%). 외관 검사 기준 이상 신호가 없습니다."
        action_lines = [
            "외관 정상 판정으로 추가 격리 조치는 불필요합니다.",
            "동일 배치의 센서 데이터 및 가열 살균 이력과 교차 확인하면 충분합니다.",
        ]
        tone = "safe"
        badge = "이상 없음"
    elif "water" in label_lower or "물" in label_lower:
        risk_line = f"CNN 모델이 '{label}'(신뢰도 {prob * 100:.1f}%)로 분류했습니다. 물 혼입 의심 외관 패턴이 감지됐습니다."
        action_lines = [
            "원료 투입 라인, 세정수 잔류 가능 구간, 밸브 전환 시점을 우선 점검하십시오.",
            "동일 로트 재검 샘플을 채취해 pH·굴절률 재측정을 권장합니다.",
        ]
        tone = "warning"
        badge = "혼입 의심"
    elif "glucose" in label_lower or "포도당" in label_lower or "mixed" in label_lower:
        risk_line = f"CNN 모델이 '{label}'(신뢰도 {prob * 100:.1f}%)로 분류했습니다. 복합 혼입 의심 외관 패턴이 감지됐습니다."
        action_lines = [
            "해당 로트 출하 후보를 즉시 보류하고 QA 승인 전 출하를 차단하십시오.",
            "원료 계량, 혼입 가능 배관, 세정제 잔류 가능 구간 및 포도당 첨가 이력을 점검하십시오.",
            "재검 샘플을 채취해 pH·굴절률·미생물 검사를 병행하십시오.",
        ]
        tone = "danger"
        badge = "복합 혼입"
    else:
        risk_line = f"CNN 모델 분류 결과: '{label}' (신뢰도 {prob * 100:.1f}%). 사전 정의된 클래스와 정확히 대응하지 않습니다."
        action_lines = [
            "Top-K 결과를 참고해 가장 유사한 클래스 기준으로 수동 확인을 진행하십시오.",
        ]
        tone = "neutral"
        badge = "수동 확인 필요"

    # OpenAI 기반 요약 시도
    try:
        from haccp_dashboard.lib.main_helpers import get_openai_chat_model, get_openai_client, get_openai_timeout_seconds
        ai_client = get_openai_client()
        if ai_client:
            prompt = (
                "다음은 HACCP 최종검사 이미지 CNN 분류 결과다. 한국어로 짧고 실무적으로 요약하라. "
                "반드시 1) 외관 판독 결과 해석 2) HACCP 위험 의미 3) 권장 조치 순으로 3개 문단 이내로 작성하고, 과장하지 마라.\n\n"
                f"분류 라벨: {label}\n"
                f"신뢰도: {prob * 100:.1f}%\n"
                f"Top-K 분류: {topk_str}\n"
            )
            response = ai_client.chat.completions.create(
                model=get_openai_chat_model(),
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "너는 HACCP 품질관리 전문가다. "
                            "이미지 CNN 분류 결과를 바탕으로 우유 품질 위험도와 공정 조치를 실무형으로 설명한다."
                        ),
                    },
                    {"role": "user", "content": prompt},
                ],
                temperature=0.2,
                max_tokens=260,
                timeout=get_openai_timeout_seconds(),
            )
            content = (response.choices[0].message.content or "").strip()
            if content:
                return {
                    "source": "openai",
                    "source_label": "OpenAI",
                    "headline": "AI 요약 브리핑 (CNN 기반)",
                    "body_lines": [line.strip() for line in content.splitlines() if line.strip()],
                    "action_lines": [],
                    "footnote": f"Top-K: {topk_str}",
                    "tone": tone,
                    "badge": badge,
                }
    except Exception:
        pass

    return {
        "source": "local",
        "source_label": "규칙 기반",
        "headline": "AI 요약 브리핑 (CNN 기반)",
        "body_lines": [risk_line],
        "action_lines": action_lines,
        "footnote": f"Top-K: {topk_str}",
        "tone": tone,
        "badge": badge,
    }


def _build_image_inference_result_panel(result: dict):
    topk = result.get("topk", []) or []
    best = topk[0] if topk else {"label": result.get("label", "unknown"), "prob": result.get("prob", 0.0)}
    label = best.get("label", "unknown")
    prob = float(best.get("prob", 0.0))

    summary = _build_cnn_ai_summary(result)
    tone = summary.get("tone", "safe")
    light_map = {"safe": "safe", "warning": "amber", "danger": "red", "neutral": "idle"}
    light_class = f"inspection-warning-light--{light_map.get(tone, 'idle')}"

    badge_tone_map = {"safe": "safe", "warning": "warning", "danger": "danger", "neutral": "neutral"}
    badge_el = _prediction_badge(summary.get("badge", label), badge_tone_map.get(tone, "neutral"))

    return html.Div(
        [
            html.Div(
                [
                    html.Div(
                        [
                            html.Div("이미지 CNN 판독", className="inspection-panel-title"),
                            html.Div("MobileNetV2 모델이 업로드 이미지를 분류했습니다.", className="inspection-panel-subtitle"),
                        ]
                    ),
                    badge_el,
                ],
                className="inspection-panel-header",
            ),
            html.Div(
                [
                    html.Div(className=f"inspection-warning-light {light_class}"),
                    html.Div(
                        [
                            html.Div(label, className="inspection-result-title"),
                            html.Div(f"신뢰도: {prob * 100:.1f}%", className="inspection-result-copy"),
                        ]
                    ),
                ],
                className="inspection-result-hero",
            ),
            html.Div(
                [
                    html.Div("Top-K 분류 결과", className="inspection-mini-label"),
                    html.Div(
                        ", ".join(
                            f"{item.get('label','?')}({float(item.get('prob',0.0))*100:.1f}%)"
                            for item in topk[:3]
                        ),
                        className="inspection-upload-file-meta",
                    ),
                ],
                className="inspection-upload-file-card",
            ),
            _build_ai_summary(summary),
        ],
        className="inspection-ai-report-card",
    )


def _result_metric_card(title, value, caption):
    return html.Div(
        [
            html.Div(title, className="inspection-result-metric-label"),
            html.Div(value, className="inspection-result-metric-value"),
            html.Div(caption, className="inspection-result-metric-caption"),
        ],
        className="inspection-result-metric-card",
    )


def _format_percentage(score):
    return f"{score * 100:.1f}%"


def _format_deviation_feature_list(prediction):
    features = prediction.get("top_deviation_features", [])
    if not features:
        return "주요 편차 피처 정보가 없습니다."
    return ", ".join(
        f"{item['name']}(정상 대비 {item['scaled_score']:+.2f})"
        for item in features[:4]
    )


def _build_local_inference_summary(prediction):
    label = prediction["label"]
    track1_score = prediction["track1_score"]
    track2_score = prediction["track2_score"]
    top_feature_line = _format_deviation_feature_list(prediction)

    if label == "no":
        risk_line = "오염 유사도가 기준선 50% 미만으로 유지되어 현재 업로드 샘플은 정상군에 더 가깝습니다."
        action_lines = [
            "즉시 출하 판정으로 넘기기보다 동일 배치 기준 샘플과 편차만 추가 확인하면 됩니다.",
            "상위 편차 피처가 허용 범위 안에서 반복되는지만 추적하면 충분합니다.",
        ]
    elif label == "bio":
        risk_line = f"오염 유사도는 {_format_percentage(track1_score)}이며, 2차 분류는 생물학 오염 방향으로 치우쳤습니다."
        action_lines = [
            "세정·살균 이력, 온도 유지 구간, 미생물 리스크 관련 공정 로그를 우선 대조하는 것이 적절합니다.",
            "동일 시간대 설비 CIP/SIP 기록과 작업자 개입 이력을 함께 확인해야 합니다.",
        ]
    else:
        risk_line = f"오염 유사도는 {_format_percentage(track1_score)}이며, 2차 분류는 화학 혼입 방향으로 더 가깝습니다."
        action_lines = [
            "원료 계량, 혼입 가능 배관, 세정제 잔류 가능 구간을 우선 점검해야 합니다.",
            "밸브 전환 시점과 세정제 플러싱 완료 여부를 배치 로그와 대조해야 합니다.",
        ]

    threshold_line = (
        f"2차 분류 임계값은 {prediction['threshold']:.2f}이며 현재 점수는 {track2_score:.3f}입니다."
        if label != "no"
        else "정상 판정 구간에서는 2차 분류를 실행하지 않으므로 오염 유형 세부 점수는 참고 수준으로 유지됩니다."
    )

    return {
        "source": "local",
        "source_label": "규칙 기반",
        "headline": "AI 요약 브리핑",
        "body_lines": [risk_line, f"주요 편차 피처: {top_feature_line}"],
        "action_lines": action_lines,
        "footnote": threshold_line,
    }


def _build_openai_inference_summary(prediction):
    from haccp_dashboard.lib.main_helpers import get_openai_chat_model, get_openai_client, get_openai_timeout_seconds

    local_summary = _build_local_inference_summary(prediction)
    ai_client = get_openai_client()
    if not ai_client:
        return local_summary

    try:
        prompt = (
            "다음은 HACCP 최종검사 추론 결과다. 한국어로 짧고 실무적으로 요약하라. "
            "반드시 1) 위험 해석 2) 주요 편차 의미 3) 권장 조치 순으로 3개 문단 이내로 작성하고, 과장하지 마라.\n\n"
            f"판정 라벨: {prediction['label']}\n"
            f"오염 유사도: {_format_percentage(prediction['track1_score'])}\n"
            f"생물학 유사도 참고치: {_format_percentage(max(0.0, 1.0 - prediction['track2_score']) if prediction['label'] != 'no' else 0.0)}\n"
            f"화학 유사도 참고치: {_format_percentage(prediction['track2_score'] if prediction['label'] != 'no' else 0.0)}\n"
            f"행 수: {prediction['rows']}\n"
            f"피처 수: {prediction['feature_count']}\n"
            f"축약 방식: {prediction.get('aggregation_mode', 'unknown')}\n"
            f"주요 편차 피처: {_format_deviation_feature_list(prediction)}\n"
            f"임계값: {prediction['threshold']:.2f}"
        )
        response = ai_client.chat.completions.create(
            model=get_openai_chat_model(),
            messages=[
                {
                    "role": "system",
                    "content": (
                        "너는 HACCP 품질관리 전문가다. "
                        "답변은 짧고 명확해야 하며, 점수 해석과 공정 조치 우선순위를 실무형으로 설명한다."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            temperature=0.2,
            max_tokens=280,
            timeout=get_openai_timeout_seconds(),
        )
        content = (response.choices[0].message.content or "").strip()
        if not content:
            return local_summary
        return {
            "source": "openai",
            "source_label": "OpenAI",
            "headline": "AI 요약 브리핑",
            "body_lines": [line.strip() for line in content.splitlines() if line.strip()],
            "action_lines": [],
            "footnote": f"주요 편차 피처: {_format_deviation_feature_list(prediction)}",
        }
    except Exception:
        fallback = dict(local_summary)
        fallback["footnote"] = f"{local_summary['footnote']} 외부 AI 호출 실패로 규칙 기반 브리핑을 사용했습니다."
        return fallback


def _build_ai_summary(summary_payload):
    return html.Div(
        [
            html.Div(
                [
                    html.Div(summary_payload["headline"], className="inspection-mini-label"),
                    _prediction_badge(summary_payload.get("source_label", "규칙 기반"), "neutral" if summary_payload.get("source") != "openai" else "safe"),
                ],
                className="inspection-inline-label-row",
            ),
            *[html.Div(line, className="inspection-result-copy") for line in summary_payload.get("body_lines", [])],
            *[html.Div(f"조치: {line}", className="inspection-result-copy") for line in summary_payload.get("action_lines", [])],
            html.Div(summary_payload.get("footnote", ""), className="inspection-result-copy inspection-result-copy--muted"),
        ],
        className="inspection-note-box",
    )


def _build_inference_result_panel(result, summary_payload):
    meta = PREDICTION_META[result["label"]]
    contamination_similarity = result["track1_score"]
    bio_similarity = max(0.0, 1.0 - result["track2_score"]) if result["label"] != "no" else 0.0
    chem_similarity = result["track2_score"] if result["label"] != "no" else 0.0

    return html.Div(
        [
            html.Div(
                [
                    html.Div(
                        [
                            html.Div("AI 오염 유사도 분석", className="inspection-panel-title"),
                            html.Div(meta["description"], className="inspection-panel-subtitle"),
                        ]
                    ),
                    _prediction_badge(meta["badge"], meta["tone"]),
                ],
                className="inspection-panel-header",
            ),
            html.Div(
                [
                    html.Div(className=f"inspection-warning-light inspection-warning-light--{meta['light']}"),
                    html.Div(
                        [
                            html.Div(meta["title"], className="inspection-result-title"),
                            html.Div(
                                f"입력 {result['rows']:,}행 · 피처 {result['feature_count']}개 기준으로 판독했습니다.",
                                className="inspection-result-copy",
                            ),
                        ]
                    ),
                ],
                className="inspection-result-hero",
            ),
            html.Div(
                [
                    _result_metric_card("오염 유사도", _format_percentage(contamination_similarity), "1차 정상/오염 분류 score"),
                    _result_metric_card("생물학 유사도", _format_percentage(bio_similarity), "2차 분류 역산 score"),
                    _result_metric_card("화학 유사도", _format_percentage(chem_similarity), "2차 분류 직접 score"),
                ],
                className="inspection-result-metric-grid",
            ),
            html.Div(
                [
                    html.Div("입력 피처 미리보기", className="inspection-mini-label"),
                    html.Div(
                        ", ".join(result["feature_columns"][:8]),
                        className="inspection-upload-file-meta",
                    ),
                    html.Div(
                        f"축약 방식: {result.get('aggregation_mode', 'unknown')} | 주요 편차: {_format_deviation_feature_list(result)}",
                        className="inspection-upload-file-meta",
                    ),
                ],
                className="inspection-upload-file-card",
            ),
            _build_ai_summary(summary_payload),
        ],
        className="inspection-ai-report-card",
    )


def _decode_csv_upload(contents):
    import pandas as pd  # type: ignore

    if not contents:
        raise ValueError("CSV 파일이 업로드되지 않았습니다.")

    content_type, content_string = contents.split(",", 1)
    del content_type
    decoded = base64.b64decode(content_string)
    return pd.read_csv(io.StringIO(decoded.decode("utf-8-sig")))


def _decode_image_upload(contents):
    if not contents:
        raise ValueError("이미지 파일이 업로드되지 않았습니다.")

    _, content_string = contents.split(",", 1)
    return base64.b64decode(content_string)


def _build_metric_cards(metrics):
    metrics = metrics or {}
    return [
        _product_card("총검사량", f"{float(metrics.get('total_q_in', 0.0)):.0f}", "장", "검사 대상 이미지 프레임 총수", "#3b82f6", is_main=True),
        _product_card("순수우유", f"{float(metrics.get('pure_milk', 0.0)):.0f}", "장", "혼입 없이 정상으로 분류된 이미지 프레임", "#22c55e"),
        _product_card("우유 + 물", f"{float(metrics.get('milk_water', 0.0)):.0f}", "장", "우유와 물 혼합으로 분류된 이미지 프레임", "#f59e0b"),
        _product_card("우유 + 물 + 포도당", f"{float(metrics.get('milk_water_glucose', 0.0)):.0f}", "장", "우유, 물, 포도당 혼합으로 분류된 이미지 프레임", "#ef4444"),
        _product_card("최종제품출하량", f"{float(metrics.get('shipment_volume', 0.0)):.0f}", "장", "정상 판정으로 출하 가능 처리된 이미지 프레임", "#059669", is_main=True),
    ]


_RECORD_TONE = {"blue": "info", "red": "danger", "yellow": "warn", "green": "ok"}

def _record_badge(label, tone):
    ds_tone = _RECORD_TONE.get(tone, "info")
    return html.Span(label, className=f"ds-badge ds-badge--{ds_tone} ds-badge--sm")


def _derive_record_flags(row):
    contamination_label = row["contamination_label"]
    is_water_mixed = contamination_label in {"화학", "미생물"}
    is_glucose_mixed = contamination_label == "미생물"

    if contamination_label == "화학":
        contamination_badge = _record_badge("화학", "yellow")
    elif contamination_label == "미생물":
        contamination_badge = _record_badge("미생물", "red")
    else:
        contamination_badge = _record_badge("정상", "blue")
    water_badge = _record_badge("혼합", "red") if is_water_mixed else _record_badge("없음", "blue")
    glucose_badge = _record_badge("혼합", "red") if is_glucose_mixed else _record_badge("없음", "blue")
    # 최종제품공정(이미지/샘플링) 배치 판정 공통 규칙에 맞춰 risk_level을 우선 사용하고,
    # 없을 때만 오염 라벨(화학=의심, 미생물=확정 부적합)로 보수적으로 복원합니다.
    risk_level = row.get("risk_level")
    if not risk_level:
        if contamination_label == "미생물":
            risk_level = "위험"
        elif contamination_label == "화학":
            risk_level = "경고"
        else:
            risk_level = "정상"
    if risk_level == "위험":
        judgement = _record_badge("출하 보류", "red")
    elif risk_level == "경고":
        judgement = _record_badge("보류(재검)", "yellow")
    else:
        judgement = _record_badge("출하 가능", "green")
    return contamination_badge, water_badge, glucose_badge, judgement


def _inspection_record_header():
    columns = ["ID", "배치", "날짜", "오염 여부", "물 혼합 여부", "pH", "포도당 혼합 여부", "판정"]
    return html.Tr(
        [
            html.Th(
                column,
                style={"padding": "12px 14px", "fontSize": "12px", "fontWeight": "700",
                       "color": "#64748b", "textAlign": "center",
                       "borderBottom": "1px solid #dde3ec",
                       "backgroundColor": "#f8fafc"},
            )
            for column in columns
        ]
    )


def _build_inprogress_badge():
    return html.Span("공정 진행 중",
                      className="ds-badge ds-badge--idle ds-badge--sm")


def _build_waiting_badge():
    return html.Span("검사 대기",
                      className="ds-badge ds-badge--info ds-badge--sm")


def _inspection_record_rows(period, target_date=None):
    from haccp_dashboard.lib import dashboard_demo as demo

    rows = []

    # 현재 공정 중 배치 – 검사 대기 표시
    try:
        from haccp_dashboard.utils.state_manager import get_per_line_states
        line_states = get_per_line_states()
        for line_id, s in sorted(line_states.items()):
            batch_name = s.get("batch_name", "-")
            stage_label = s.get("stage_label", "-")
            if not batch_name or batch_name == "-":
                continue
            rows.append(html.Tr(
                [
                    html.Td(f"L{line_id}-진행중", style={"padding": "13px 10px", "fontSize": "12px", "fontWeight": "700", "color": "#334155", "textAlign": "center"}),
                    html.Td(batch_name, style={"textAlign": "center", "fontSize": "12px", "fontWeight": "700", "color": "#334155"}),
                    html.Td("진행 중", style={"textAlign": "center", "fontSize": "12px", "color": "#334155"}),
                    html.Td(_build_inprogress_badge(), style={"textAlign": "center"}),
                    html.Td(_build_inprogress_badge(), style={"textAlign": "center"}),
                    html.Td("-", style={"textAlign": "center", "fontSize": "12px", "color": "#94a3b8"}),
                    html.Td(_build_inprogress_badge(), style={"textAlign": "center"}),
                    html.Td(_build_waiting_badge(), style={"textAlign": "center"}),
                ],
                style={"borderBottom": "1px solid #dbeafe", "backgroundColor": "#f8faff"},
            ))
    except Exception:
        pass

    for row in demo.get_final_inspection_rows(period, target_date):
        contamination_badge, water_badge, glucose_badge, judgement = _derive_record_flags(row)
        rows.append(
            html.Tr(
                [
                    html.Td(row["report_id"], style={"padding": "13px 10px", "fontSize": "12px", "fontWeight": "700", "color": "#334155", "textAlign": "center"}),
                    html.Td(row["batch_name"], style={"textAlign": "center", "fontSize": "12px", "fontWeight": "700", "color": "#334155"}),
                    html.Td(row["date"], style={"textAlign": "center", "fontSize": "12px", "color": "#334155"}),
                    html.Td(contamination_badge, style={"textAlign": "center"}),
                    html.Td(water_badge, style={"textAlign": "center"}),
                    html.Td(f"{row['final_ph']:.1f}", style={"textAlign": "center", "fontSize": "12px", "color": "#334155"}),
                    html.Td(glucose_badge, style={"textAlign": "center"}),
                    html.Td(judgement, style={"textAlign": "center"}),
                ],
                style={"borderBottom": "1px solid #f1f5f9", "backgroundColor": "white"},
            )
        )
    return rows


def _point_ai_report(period, batch_id, round_number, target_date=None):
    from haccp_dashboard.lib import dashboard_demo as demo

    rounds_total = demo.get_configured_runs_per_day()
    try:
        from haccp_dashboard.lib.main_helpers import get_dashboard_current_lot_index

        current_lot = int(get_dashboard_current_lot_index())
    except Exception:
        current_lot = None

    display_rounds = int(rounds_total)
    completed_rounds = int(rounds_total)
    if current_lot is not None and 1 <= int(current_lot) <= int(rounds_total):
        display_rounds = min(int(rounds_total), int(current_lot))
        completed_rounds = max(0, display_rounds - 1)

    point_summary = demo.get_final_inspection_batch_round_summary(
        period,
        batch_count=3,
        rounds=display_rounds,
        target_date=target_date,
    )
    if not point_summary:
        return html.Div(
            "검사 포인트를 선택하면 AI 요약 보고서가 표시됩니다.",
            style={"fontSize": "13px", "color": "#6b7280"},
        )

    selected = next(
        (item for item in point_summary if item["batch_id"] is not None and int(item["batch_id"]) == int(batch_id) and item["round"] == round_number),
        None,
    )
    if not selected:
        return html.Div(
            "선택한 포인트 정보를 찾을 수 없습니다.",
            style={"fontSize": "13px", "color": "#6b7280"},
        )

    batch_label = selected.get("batch_name", f"BATCH-{int(batch_id):03d}")
    total = selected["total"]
    no_count = selected["no_count"]
    chem_count = selected["chem_count"]
    bio_count = selected["bio_count"]
    defect_count = selected["defect_count"]
    defect_rate = selected["defect_rate"]
    suspect_count = int(selected.get("suspect_count", chem_count) or 0)
    confirmed_nonconforming_count = int(selected.get("confirmed_nonconforming_count", bio_count) or 0)
    batch_risk_level = str(selected.get("risk_level") or "")
    batch_status = str(selected.get("status") or "")

    no_ratio = (no_count / total * 100.0) if total else 0.0
    chem_ratio = (chem_count / total * 100.0) if total else 0.0
    bio_ratio = (bio_count / total * 100.0) if total else 0.0

    if batch_risk_level == "위험" or confirmed_nonconforming_count >= 1:
        risk_text = "위험"
        risk_color = "#b91c1c"
        risk_comment = "확정 부적합이 1건 이상 발생해 즉시 출하 보류 및 격리/원인조사가 필요합니다."
    elif batch_risk_level == "경고" or suspect_count >= 1:
        risk_text = "경고"
        risk_color = "#b45309"
        risk_comment = "확정 부적합은 없지만 의심 샘플이 누적되어 추가 확인/재검이 필요합니다."
    else:
        risk_text = "정상"
        risk_color = "#166534"
        risk_comment = "확정 부적합과 의심 샘플이 없어 출하 가능 상태로 해석할 수 있습니다."

    if bio_count > chem_count and bio_count > 0:
        process_impact = "생물학적 혼합 비중이 더 높아 미생물 리스크 대응(세정/살균 조건) 강화를 권장합니다."
    elif chem_count > 0:
        process_impact = "물 혼합 비중이 높아 원료 라인 누수/혼입 및 계량 밸런스 점검이 우선입니다."
    else:
        process_impact = "적합 비중이 높아 공정 영향은 제한적이며 현재 제어조건 유지가 적절합니다."

    if risk_text == "위험":
        action_title = "권장 조치 (즉시 실행)"
        action_items = [
            "해당 로트 출하 후보를 즉시 보류하고 QA 승인 전 출하를 차단합니다.",
            "배치 라인 세정/살균 조건(CIP/SIP) 이행 여부를 즉시 점검합니다.",
            "재검 샘플을 우선 채취하여 판정 재확인 후 원인 이력서를 등록합니다.",
            "원인조사 결과를 이력서 및 CAPA에 등록합니다.",
        ]
        ship_status = "출하 보류"
        core_action = "격리 및 원인조사"
        haccp_view = "출하보류 + 격리"
        root_cause = "필수"
        next_step = "재검 및 CAPA 진행"
        banner_comment = f"확정 부적합 {confirmed_nonconforming_count}건 발생으로 해당배치는 출하 보류 대상입니다."
        banner_tag = "제품격리 필요"
    elif risk_text == "경고":
        action_title = "권장 조치 (재검·추가 확인)"
        action_items = [
            "의심 샘플을 분리 보관하고 동일 배치의 검사 포인트(채취 위치/시간)를 재확인합니다.",
            "동일 배치에서 재검 샘플을 추가 채취해 PASS/부적합 여부를 확정합니다.",
            "확정 부적합이 1건이라도 발생하면 즉시 출하 보류로 전환하도록 기준을 사전 공유합니다.",
            "재검 결과를 QA 검토 기록에 첨부합니다.",
        ]
        ship_status = "추가 확인"
        core_action = "재검 및 모니터링"
        haccp_view = "조건부 보류"
        root_cause = "권장"
        next_step = "재검 후 재판정"
        banner_comment = f"의심 샘플 {suspect_count}건이 누적되어 추가 확인 후 출하 여부를 결정합니다."
        banner_tag = "재검 권고"
    else:
        action_title = "권장 조치 (정상 유지)"
        action_items = [
            "현재 공정 조건과 작업 표준을 유지하고 정기 모니터링을 지속합니다.",
            "주간 단위로 배치별 편차를 점검해 조기 이상 신호를 확인합니다.",
            "표준 검교정 및 세정 점검 일정을 계획대로 수행합니다.",
            "정상 판정 결과를 출하 기록에 정상 등재합니다.",
        ]
        ship_status = "출하 가능"
        core_action = "정상 유지"
        haccp_view = "출하 가능"
        root_cause = "불필요"
        next_step = "정상 출하 진행"
        banner_comment = "확정 부적합과 의심 샘플이 없어 출하 가능 상태입니다."
        banner_tag = "정상 출하"

    soft_bg = {"위험": "#fef2f2", "경고": "#fffbeb", "정상": "#f0fdf4"}[risk_text]
    soft_border = {"위험": "#fecaca", "경고": "#fde68a", "정상": "#bbf7d0"}[risk_text]

    def _kpi_cell(label, value, color):
        return html.Div(
            [
                html.Div(label, style={"fontSize": "11.5px", "color": "#6b7280",
                                        "marginBottom": "4px", "fontWeight": "600"}),
                html.Div(value, style={"fontSize": "15px", "fontWeight": "800", "color": color}),
            ],
            style={"flex": "1", "padding": "12px 10px", "border": "1px solid #e5e7eb",
                   "borderRadius": "10px", "backgroundColor": "white", "textAlign": "center"},
        )

    def _bar_row(label, count, ratio, color):
        return html.Div(
            [
                html.Div(
                    [
                        html.Span(label, style={"fontSize": "12px", "color": "#374151"}),
                        html.Span(f"{count}건 ({ratio:.1f}%)",
                                  style={"fontSize": "12px", "color": color, "fontWeight": "700"}),
                    ],
                    style={"display": "flex", "justifyContent": "space-between", "marginBottom": "4px"},
                ),
                html.Div(
                    html.Div(
                        style={"width": f"{min(100.0, max(2.0, ratio)):.1f}%",
                                "height": "6px", "backgroundColor": color, "borderRadius": "3px"},
                    ),
                    style={"width": "100%", "height": "6px", "backgroundColor": "#f1f5f9",
                            "borderRadius": "3px", "overflow": "hidden"},
                ),
            ],
            style={"marginBottom": "10px"},
        )

    def _footer_cell(label, value, color):
        return html.Div(
            [
                html.Div(label, style={"fontSize": "11.5px", "color": "#6b7280",
                                        "marginBottom": "4px", "fontWeight": "600"}),
                html.Div(value, style={"fontSize": "14px", "fontWeight": "800", "color": color}),
            ],
            style={"flex": "1", "textAlign": "center"},
        )

    meta_text = (
        f"선택 배치: {batch_label} · 로트 {round_number}"
        if current_lot is None
        else f"선택 배치: {batch_label} · 로트 {round_number} (완료 1~{int(completed_rounds)}, 현재 로트 {int(current_lot)} 검사 대기)"
    )

    return html.Div(
        [
            html.Div("최종제품 검사 AI 요약", className="ds-ai-report-title",
                     style={"fontSize": "16px", "fontWeight": "800", "color": "#0f172a"}),
            html.Div(meta_text, className="ds-ai-report-meta",
                     style={"fontSize": "12px", "color": "#6b7280", "marginBottom": "14px"}),

            # ── KPI 4분할
            html.Div(
                [
                    _kpi_cell("배치 판정", risk_text, risk_color),
                    _kpi_cell("출하 상태", ship_status, risk_color),
                    _kpi_cell("확정 부적합", f"{confirmed_nonconforming_count}건 / {total}건", risk_color),
                    _kpi_cell("핵심 조치", core_action, risk_color),
                ],
                style={"display": "flex", "gap": "8px", "marginBottom": "14px"},
            ),

            # ── HACCP 최종 판정 배너
            html.Div(
                [
                    html.Div("HACCP 최종 판정",
                             style={"fontSize": "13px", "fontWeight": "800",
                                    "color": "#0f172a", "marginBottom": "8px"}),
                    html.Div(
                        [
                            html.Div(risk_text,
                                     style={"display": "inline-block", "padding": "6px 16px",
                                            "borderRadius": "8px", "backgroundColor": risk_color,
                                            "color": "white", "fontSize": "16px", "fontWeight": "800",
                                            "marginRight": "12px"}),
                            html.Span(banner_comment,
                                      style={"fontSize": "13px", "color": "#374151",
                                             "lineHeight": "1.5"}),
                            html.Span(banner_tag,
                                      style={"display": "inline-block", "marginLeft": "auto",
                                             "padding": "6px 12px", "border": f"1px solid {risk_color}",
                                             "borderRadius": "8px", "color": risk_color,
                                             "fontSize": "12px", "fontWeight": "700",
                                             "backgroundColor": "white"}),
                        ],
                        style={"display": "flex", "alignItems": "center", "flexWrap": "wrap",
                                "gap": "8px"},
                    ),
                ],
                style={"padding": "14px 16px", "border": f"1.5px solid {soft_border}",
                       "borderRadius": "12px", "backgroundColor": soft_bg,
                       "marginBottom": "14px"},
            ),

            # ── 2분할: 검사 결과 구성 / 위해 해석 및 공정 영향
            html.Div(
                [
                    html.Div(
                        [
                            html.Div("검사 결과 구성",
                                     style={"fontSize": "13px", "fontWeight": "800",
                                            "color": "#0f172a", "marginBottom": "10px"}),
                            _bar_row("순수 우유(적합)", no_count, no_ratio, "#16a34a"),
                            _bar_row("의심 샘플(추가 확인)", chem_count, chem_ratio, "#d97706"),
                            _bar_row("확정 부적합", bio_count, bio_ratio, "#dc2626"),
                        ],
                        style={"flex": "1", "padding": "14px 16px", "border": "1px solid #e5e7eb",
                                "borderRadius": "12px", "backgroundColor": "white"},
                    ),
                    html.Div(
                        [
                            html.Div("위해 해석 및 공정 영향",
                                     style={"fontSize": "13px", "fontWeight": "800",
                                            "color": "#0f172a", "marginBottom": "10px"}),
                            html.Div(f"위험도: {risk_text}",
                                     style={"fontSize": "13px", "fontWeight": "800",
                                             "color": risk_color, "marginBottom": "8px"}),
                            html.Ul(
                                [
                                    html.Li(process_impact,
                                            style={"fontSize": "12px", "color": "#374151",
                                                    "marginBottom": "6px", "lineHeight": "1.5"}),
                                    html.Li("세정/살균 조건 및 배치 라인 위생상태 확인 권고"
                                            if risk_text != "정상"
                                            else "현재 제어조건 유지 및 정기 모니터링 지속",
                                            style={"fontSize": "12px", "color": "#374151",
                                                    "lineHeight": "1.5"}),
                                ],
                                style={"paddingLeft": "18px", "margin": 0, "marginBottom": "10px"},
                            ),
                            html.Div(
                                ("출하 차단 권고" if risk_text == "위험"
                                 else ("재검 권고" if risk_text == "경고" else "출하 진행 가능")),
                                style={"display": "inline-block", "padding": "6px 12px",
                                        "border": f"1px solid {risk_color}", "borderRadius": "8px",
                                        "color": risk_color, "fontSize": "12px",
                                        "fontWeight": "700", "backgroundColor": "white"},
                            ),
                        ],
                        style={"flex": "1", "padding": "14px 16px", "border": "1px solid #e5e7eb",
                                "borderRadius": "12px", "backgroundColor": "white"},
                    ),
                ],
                style={"display": "flex", "gap": "10px", "marginBottom": "14px"},
            ),

            # ── 권장 조치 + Footer (토글)
            html.Details(
                [
                    html.Summary(
                        [
                            html.Span("상세 조치 및 HACCP 후속 단계",
                                      style={"fontSize": "13px", "fontWeight": "700",
                                             "color": "#0f172a"}),
                            html.Span("펼치기 / 접기",
                                      style={"fontSize": "11.5px", "color": "#6b7280",
                                             "marginLeft": "auto"}),
                        ],
                        style={"display": "flex", "alignItems": "center",
                                "padding": "10px 14px", "border": "1px solid #e5e7eb",
                                "borderRadius": "10px", "backgroundColor": "#f8fafc",
                                "cursor": "pointer", "listStyle": "none",
                                "userSelect": "none"},
                    ),
                    html.Div(
                        [
                            # ── 권장 조치 (번호 목록)
                            html.Div(
                                [
                                    html.Div(action_title,
                                             style={"fontSize": "13px", "fontWeight": "800",
                                                    "color": "#0f172a", "marginBottom": "10px"}),
                                    html.Div(
                                        [
                                            html.Div(
                                                [
                                                    html.Div(str(i + 1),
                                                             style={"width": "22px", "height": "22px",
                                                                    "borderRadius": "6px",
                                                                    "backgroundColor": "#f1f5f9",
                                                                    "color": "#475569", "fontSize": "12px",
                                                                    "fontWeight": "800",
                                                                    "display": "flex", "alignItems": "center",
                                                                    "justifyContent": "center",
                                                                    "marginRight": "10px", "flex": "0 0 auto"}),
                                                    html.Span(item, style={"fontSize": "12.5px",
                                                                           "color": "#374151",
                                                                           "lineHeight": "1.5"}),
                                                ],
                                                style={"display": "flex", "alignItems": "flex-start",
                                                        "padding": "8px 0",
                                                        "borderTop": "1px solid #f1f5f9" if i > 0 else "none"},
                                            )
                                            for i, item in enumerate(action_items)
                                        ],
                                    ),
                                ],
                                style={"padding": "14px 16px", "border": "1px solid #e5e7eb",
                                        "borderRadius": "12px", "backgroundColor": "white",
                                        "marginBottom": "14px"},
                            ),
                            # ── Footer 3분할
                            html.Div(
                                [
                                    _footer_cell("HACCP 관점", haccp_view, risk_color),
                                    _footer_cell("원인 조사", root_cause, risk_color),
                                    _footer_cell("다음 단계", next_step,
                                                 "#16a34a" if risk_text == "정상" else risk_color),
                                ],
                                style={"display": "flex", "gap": "8px", "padding": "14px 16px",
                                       "border": "1px solid #e5e7eb", "borderRadius": "12px",
                                       "backgroundColor": "white"},
                            ),
                        ],
                        style={"marginTop": "12px"},
                    ),
                ],
                style={"width": "100%"},
            ),
        ]
    )


def _build_lot_status_grid(point_summary, completed_rounds, current_lot, rounds_total, target_date=None):
    """
    라인 × 로트 상태 그리드 카드 (HTML 기반)
    """
    import datetime
    from haccp_dashboard.lib.process_spec import DAILY_OPERATION_START_HOUR, TIME_LOT_MINUTES

    today_str = target_date or datetime.date.today().strftime("%Y-%m-%d")
    rounds_total = int(rounds_total)
    completed = int(completed_rounds)

    # 현재 공정 진행 중인 로트까지만 표시 (그 이후 미래 열은 제외)
    display_lots_count = int(current_lot) if (current_lot is not None and 1 <= int(current_lot) <= rounds_total) else rounds_total

    if not point_summary:
        return html.Div("데이터 없음", style={"fontSize": "13px", "color": "#9ca3af", "padding": "20px"})

    line_ids = sorted(set(int(item["line_id"]) for item in point_summary if item.get("line_id") is not None))
    lots = list(range(1, display_lots_count + 1))
    n_lines = len(line_ids)

    status_map = {}
    for item in point_summary:
        if item.get("line_id") is not None:
            status_map[(int(item["line_id"]), int(item["round"]))] = item

    if current_lot is not None and 1 <= current_lot <= rounds_total:
        subtitle = f"{today_str} · {n_lines}개 라인 · 공정 1~{completed}회 완료 / 공정 {current_lot}회 진행 중"
    else:
        subtitle = f"{today_str} · {n_lines}개 라인 · 공정 1~{rounds_total}회 완료"

    def _lot_start_label(lot_num: int) -> str:
        total_minutes = int(DAILY_OPERATION_START_HOUR) * 60 + (lot_num - 1) * int(TIME_LOT_MINUTES)
        hh = (total_minutes // 60) % 24
        mm = total_minutes % 60
        return f"{hh:02d}:{mm:02d}"

    STATUS_STYLE = {
        "정상": {"bg": "#f0fdf4", "border": "#bbf7d0", "icon": "✔", "icon_color": "#22c55e", "label": "정상", "label_color": "#166534"},
        "경고": {"bg": "#fff7ed", "border": "#fed7aa", "icon": "⚠", "icon_color": "#f59e0b", "label": "경고", "label_color": "#b45309"},
        "위험": {"bg": "#fef2f2", "border": "#fecaca", "icon": "✖", "icon_color": "#ef4444", "label": "부적합", "label_color": "#b91c1c"},
        "대기": {"bg": "#f9fafb", "border": "#e5e7eb", "icon": "⏱", "icon_color": "#9ca3af", "label": "검사 대기", "label_color": "#9ca3af"},
    }

    def _make_cell(line_id, lot_num):
        is_pending = current_lot is not None and lot_num >= int(current_lot)
        item = status_map.get((line_id, lot_num))
        if is_pending:
            s = STATUS_STYLE["대기"]
        else:
            risk = (item["risk_level"] if item else None) or "정상"
            s = STATUS_STYLE.get(risk, STATUS_STYLE["정상"])
        batch_id = item["batch_id"] if (item and item.get("batch_id") is not None) else 0
        cell_inner = html.Div(
            [
                html.Div(s["icon"], style={"fontSize": "20px", "color": s["icon_color"], "lineHeight": "1"}),
                html.Div(s["label"], style={"fontSize": "11px", "fontWeight": "700", "color": s["label_color"], "marginTop": "5px"}),
            ],
            style={"display": "flex", "flexDirection": "column", "alignItems": "center", "justifyContent": "center", "padding": "12px 8px"},
        )
        if is_pending:
            return html.Td(
                cell_inner,
                style={
                    "backgroundColor": s["bg"],
                    "border": f"1.5px solid {s['border']}",
                    "borderRadius": "10px",
                    "textAlign": "center",
                    "cursor": "default",
                },
            )
        return html.Td(
            html.Button(
                cell_inner,
                id={"type": "lot-grid-btn", "key": f"{line_id}_{lot_num}_{batch_id}"},
                n_clicks=0,
                style={
                    "backgroundColor": s["bg"],
                    "border": f"1.5px solid {s['border']}",
                    "borderRadius": "10px",
                    "textAlign": "center",
                    "width": "100%",
                    "cursor": "pointer",
                    "padding": "0",
                },
            ),
            style={"padding": "0"},
        )

    header_cells = [html.Th("", style={"width": "56px", "padding": "0 4px"})]
    for lot in lots:
        is_current = current_lot is not None and lot == int(current_lot)
        header_cells.append(
            html.Th(
                [
                    html.Div(f"공정 {lot}회", style={"fontWeight": "700"}),
                    html.Div(
                        _lot_start_label(lot),
                        style={"fontWeight": "400", "color": "#c2410c" if is_current else "#6b7280"},
                    ),
                ],
                style={
                    "textAlign": "center",
                    "fontSize": "11.5px",
                    "color": "#c2410c" if is_current else "#374151",
                    "padding": "6px 2px",
                    "borderBottom": "2px solid #fb923c" if is_current else "none",
                },
            )
        )

    data_rows = []
    for line_id in line_ids:
        row_cells = [
            html.Td(
                f"라인 {line_id}",
                style={"fontWeight": "700", "fontSize": "13px", "color": "#374151", "paddingRight": "12px", "paddingLeft": "4px", "whiteSpace": "nowrap"},
            )
        ]
        for lot in lots:
            row_cells.append(_make_cell(line_id, lot))
        data_rows.append(html.Tr(row_cells, style={"verticalAlign": "middle"}))

    legend_defs = [
        ("✔", "#22c55e", "#f0fdf4", "#bbf7d0", "정상"),
        ("⚠", "#f59e0b", "#fff7ed", "#fed7aa", "경고"),
        ("✖", "#ef4444", "#fef2f2", "#fecaca", "부적합"),
        ("⏱", "#9ca3af", "#f9fafb", "#e5e7eb", "검사 대기"),
    ]
    legend_elements = [
        html.Div(
            [
                html.Span(icon, style={"fontSize": "14px", "color": icon_c, "marginRight": "5px"}),
                html.Span(lbl, style={"fontSize": "12px", "fontWeight": "700", "color": "#374151"}),
            ],
            style={
                "display": "flex", "alignItems": "center",
                "backgroundColor": bg, "border": f"1px solid {border}",
                "borderRadius": "6px", "padding": "5px 12px", "marginRight": "8px", "marginBottom": "4px",
            },
        )
        for icon, icon_c, bg, border, lbl in legend_defs
    ]

    return html.Div(
        [
            html.Div("라인별 공정회차 최종검사 판정 현황",
                      className="ds-section-header",
                      style={"marginBottom": "4px"}),
            html.Div(subtitle, className="ds-section-sub",
                      style={"marginBottom": "16px"}),
            html.Div(
                html.Table(
                    [html.Thead(html.Tr(header_cells)), html.Tbody(data_rows)],
                    style={"borderCollapse": "separate", "borderSpacing": "4px",
                           "width": "100%", "tableLayout": "fixed"},
                ),
                style={"overflowX": "hidden", "width": "100%"},
            ),
            html.Div(legend_elements, style={"display": "flex", "flexWrap": "wrap", "marginTop": "16px"}),
            html.Div(
                [
                    html.Div(
                        [
                            html.Span("↖ ", style={"fontSize": "13px"}),
                            html.Span("셀 클릭 시 해당 시점의 판정 상세 정보 확인", style={"fontSize": "12px", "color": "#6b7280"}),
                        ],
                        style={"display": "flex", "alignItems": "center"},
                    ),
                ],
                style={"display": "flex", "justifyContent": "space-between", "marginTop": "12px", "flexWrap": "wrap", "gap": "8px"},
            ),
        ],
        className="ds-card",
        style={"marginBottom": "14px"},
    )


def layout():
    from haccp_dashboard.lib import dashboard_demo as demo

    rounds_total = demo.get_configured_runs_per_day()
    try:
        from haccp_dashboard.lib.main_helpers import get_dashboard_current_lot_index

        current_lot = int(get_dashboard_current_lot_index())
    except Exception:
        current_lot = None

    completed_rounds = int(rounds_total)
    if current_lot is not None and 1 <= int(current_lot) <= int(rounds_total):
        completed_rounds = max(0, int(current_lot) - 1)

    return html.Div(
        [
            dcc.Store(id="final-inspection-image-upload-store"),
            html.Div(
                [
                    html.Div(
                        [
                            html.Div(
                                [
                                    html.H2("최종 품질 검사", className="section-title page"),
                                    dcc.Store(id="final-inspection-period-selector", data=DEFAULT_PERIOD),
                                    dcc.Store(id="final-inspection-date-selector", data=None),
                                ],
                                style={"display": "flex", "justifyContent": "space-between", "alignItems": "center"},
                            ),
                            html.Div(
                                id="final-inspection-cards",
                                children=_build_metric_cards({}),
                                className="ds-kpi-grid",
                            ),
                            html.Div(
                                demo.get_final_inspection_dataset_validation_message(),
                                className="inspection-sampling-note",
                            ),
                            html.Div(
                                "HACCP 운영 기준: 공정 1회마다 배치 1건을 샘플링하여 최종 제품 CCP 모니터링 기록으로 관리합니다. "
                                "(라인 3개 × 일 8회 공정 × 5일 = 120 배치, 배치당 50장 캡처 → 총 6,000장)",
                                className="inspection-sampling-note",
                                style={"marginTop": "4px", "color": "#6b7280", "fontSize": "12px"},
                            ),
                        ],
                        className="screen-zone top",
                    ),
                    html.Div(
                        [
                            html.Div(
                                [
                                    dcc.Store(id="inspection-grid-click-store", data=None),
                                    html.Div(
                                        id="inspection-lot-status-grid",
                                        children=html.Div(
                                            "로딩 중...",
                                            style={"fontSize": "13px", "color": "#9ca3af", "padding": "20px"},
                                        ),
                                    ),
                                ],
                                className="inspection-flow-panel",
                            ),
                            html.Div(
                                id="inspection-ai-report",
                                children=html.Div(
                                    "셀을 클릭하면 해당 로트의 AI 요약 보고서가 표시됩니다.",
                                    style={"fontSize": "13px", "color": "#6b7280"},
                                ),
                                className="inspection-ai-report-card",
                            ),
                        ],
                        style={"minWidth": "0"},
                        className="screen-zone middle inspection-analysis-shell",
                    ),
                    html.Div(
                        [
                            html.H2(
                                "이미지 CNN 판독",
                                style={
                                    "margin": "0 0 14px 0",
                                    "fontSize": "16px",
                                    "fontWeight": "700",
                                    "color": "#0f172a",
                                },
                            ),
                            html.Div(
                                [
                                    html.Div(
                                        [
                                            html.Div(
                                                _build_image_upload_status_panel(),
                                                id="final-inspection-image-upload-summary",
                                            ),
                                            dcc.Upload(
                                                id="final-inspection-image-upload",
                                                children=html.Div(
                                                    [
                                                        html.Div("이미지 업로드", className="inspection-upload-drop-title"),
                                                        html.Div(
                                                            "최종 검사 이미지를 드래그하거나 클릭해 선택합니다.",
                                                            className="inspection-upload-drop-copy",
                                                        ),
                                                    ]
                                                ),
                                                className="inspection-upload-dropzone",
                                                accept="image/*",
                                                multiple=False,
                                            ),
                                            html.Button(
                                                "판독 실행",
                                                id="final-inspection-run-image-inference",
                                                n_clicks=0,
                                                disabled=True,
                                                className="inspection-run-button",
                                            ),
                                        ],
                                        className="inspection-model-card",
                                    ),
                                    html.Div(
                                        id="final-inspection-image-inference-result",
                                        children=_build_image_inference_idle_panel(),
                                        className="inspection-model-result-shell",
                                    ),
                                ],
                                className="inspection-model-shell",
                            ),
                        ],
                        style={
                            "background": "#ffffff",
                            "border": "1px solid #dde3ec",
                            "borderRadius": "12px",
                            "padding": "20px 24px",
                            "marginBottom": "16px",
                            "boxShadow": "0 1px 4px rgba(13,27,42,0.06),0 4px 14px rgba(13,27,42,0.05)",
                        },
                    ),
                    html.Div(
                        [
                            html.Div(
                                [
                                    html.Div("최종검사 기록", className="section-title"),
                                    html.Button(
                                        "초기화",
                                        n_clicks=0,
                                        style={
                                            "border": "1px solid #e2b24a",
                                            "background": "#f8c45c",
                                            "color": "#6f4d0c",
                                            "borderRadius": "4px",
                                            "padding": "5px 10px",
                                            "fontSize": "11px",
                                            "fontWeight": "700",
                                            "cursor": "default",
                                        },
                                    ),
                                ],
                                style={"display": "flex", "justifyContent": "space-between", "alignItems": "center", "marginBottom": "10px"},
                            ),
                            html.Div(
                                html.Table(
                                    style={"width": "100%", "fontSize": "12px", "tableLayout": "fixed", "borderCollapse": "separate", "borderSpacing": "0"},
                                    children=[
                                        html.Thead(_inspection_record_header()),
                                        html.Tbody(id="final-inspection-record-body", children=_inspection_record_rows(DEFAULT_PERIOD, None)),
                                    ],
                                ),
                                className="compact-scroll",
                                style={"maxHeight": "280px", "overflowY": "auto", "border": "1px solid #dde3ec", "borderRadius": "14px", "background": "white"},
                            ),
                        ],
                        className="screen-zone bottom chart-box",
                    ),
                ],
                className="dashboard-container dashboard-screen",
            )
        ],
        style={"height": "100%", "padding": "0"},
    )


@callback(
    Output("final-inspection-date-selector", "data"),
    Input("final-inspection-period-selector", "data"),
)
def update_final_inspection_date_options(period):
    from haccp_dashboard.lib import dashboard_demo as demo

    dates = demo.get_final_inspection_available_dates(period or DEFAULT_PERIOD)
    return dates[0] if dates else None


@callback(
    Output("final-inspection-cards", "children"),
    Output("final-inspection-record-body", "children"),
    Output("inspection-lot-status-grid", "children"),
    Output("inspection-grid-click-store", "data", allow_duplicate=True),
    Input("final-inspection-period-selector", "data"),
    Input("final-inspection-date-selector", "data"),
    prevent_initial_call="initial_duplicate",
)
def update_final_inspection(period, target_date):
    from haccp_dashboard.lib import dashboard_demo as demo

    metrics = demo.get_final_inspection_metrics(period, target_date)
    rounds_total = demo.get_configured_runs_per_day()
    try:
        from haccp_dashboard.lib.main_helpers import get_dashboard_current_lot_index

        current_lot = int(get_dashboard_current_lot_index())
    except Exception:
        current_lot = None

    completed_rounds = int(rounds_total)
    if current_lot is not None and 1 <= int(current_lot) <= int(rounds_total):
        completed_rounds = max(0, int(current_lot) - 1)

    point_summary = demo.get_final_inspection_batch_round_summary(
        period,
        batch_count=3,
        rounds=rounds_total,
        target_date=target_date,
    )

    return (
        _build_metric_cards(metrics),
        _inspection_record_rows(period, target_date),
        _build_lot_status_grid(point_summary, completed_rounds, current_lot, rounds_total, target_date),
        None,
    )


@callback(
    Output("inspection-grid-click-store", "data"),
    Input({"type": "lot-grid-btn", "key": ALL}, "n_clicks"),
    State({"type": "lot-grid-btn", "key": ALL}, "id"),
    prevent_initial_call=True,
)
def handle_grid_cell_click(n_clicks_list, id_list):
    triggered = dash.callback_context.triggered_id
    if not triggered or not isinstance(triggered, dict):
        return dash.no_update
    key = triggered.get("key", "")
    parts = key.split("_")
    if len(parts) < 3:
        return dash.no_update
    try:
        line_id = int(parts[0])
        lot_num = int(parts[1])
        batch_id = int(parts[2]) if parts[2] != "0" else None
    except (ValueError, IndexError):
        return dash.no_update
    return {"line_id": line_id, "lot": lot_num, "batch_id": batch_id}


@callback(
    Output("inspection-ai-report", "children"),
    Input("inspection-grid-click-store", "data"),
    State("final-inspection-period-selector", "data"),
    State("final-inspection-date-selector", "data"),
)
def update_ai_report_from_grid(click_data, period, target_date):
    if not click_data:
        return html.Div(
            "셀을 클릭하면 해당 로트의 AI 요약 보고서가 표시됩니다.",
            style={"fontSize": "13px", "color": "#6b7280"},
        )
    try:
        from haccp_dashboard.lib import dashboard_demo as demo

        rounds_total = demo.get_configured_runs_per_day()
        try:
            from haccp_dashboard.lib.main_helpers import get_dashboard_current_lot_index
            current_lot = int(get_dashboard_current_lot_index())
        except Exception:
            current_lot = None

        completed_rounds = int(rounds_total)
        if current_lot is not None and 1 <= int(current_lot) <= int(rounds_total):
            completed_rounds = max(0, int(current_lot) - 1)

        batch_id = click_data.get("batch_id")
        lot_num = int(click_data.get("lot", 0))
        if batch_id is None or lot_num < 1 or lot_num > completed_rounds:
            return html.Div(
                "검사 대기 중인 로트는 보고서가 없습니다.",
                style={"fontSize": "13px", "color": "#6b7280"},
            )
        return _point_ai_report(period or DEFAULT_PERIOD, batch_id, lot_num, target_date)
    except Exception as exc:
        return html.Div(str(exc), style={"fontSize": "12px", "color": "#ef4444"})


@callback(
    Output("final-inspection-image-upload-store", "data"),
    Output("final-inspection-image-upload", "children"),
    Output("final-inspection-image-upload-summary", "children"),
    Output("final-inspection-run-image-inference", "disabled"),
    Input("final-inspection-image-upload", "contents"),
    State("final-inspection-image-upload", "filename"),
)
def cache_uploaded_image(contents, filename):
    if not contents:
        return (
            None,
            html.Div(
                [
                    html.Div("이미지 업로드", className="inspection-upload-drop-title"),
                    html.Div("최종 검사 이미지를 드래그하거나 클릭해 선택합니다.", className="inspection-upload-drop-copy"),
                ]
            ),
            _build_image_upload_status_panel(),
            True,
        )

    try:
        image_bytes = _decode_image_upload(contents)
        payload = {
            "filename": filename or "uploaded.jpg",
            "bytes_b64": base64.b64encode(image_bytes).decode("ascii"),
        }
        upload_children = html.Div(
            [
                html.Div("업로드 완료", className="inspection-upload-drop-title"),
                html.Div(f"{payload['filename']}", className="inspection-upload-drop-copy"),
            ]
        )
        return payload, upload_children, _build_image_upload_status_panel(upload_data=payload), False
    except Exception as exc:
        return (
            None,
            html.Div(
                [
                    html.Div("업로드 실패", className="inspection-upload-drop-title"),
                    html.Div(str(exc), className="inspection-upload-drop-copy"),
                ]
            ),
            _build_image_upload_status_panel(error_message=str(exc)),
            True,
        )


@callback(
    Output("final-inspection-image-inference-result", "children"),
    Input("final-inspection-run-image-inference", "n_clicks"),
    State("final-inspection-image-upload-store", "data"),
    prevent_initial_call=True,
)
def run_uploaded_image_inference(n_clicks, upload_data):
    if not upload_data:
        return _build_image_inference_idle_panel()

    if not n_clicks:
        return _build_image_inference_idle_panel()

    try:
        image_bytes = base64.b64decode(upload_data.get("bytes_b64", "") or "")
        result = predict_image_class(image_bytes=image_bytes, topk=3)
        return _build_image_inference_result_panel(result)
    except Exception as exc:
        return html.Div(
            [
                html.Div("이미지 CNN 판독", className="inspection-panel-title"),
                html.Div("판독 중 오류가 발생했습니다.", className="inspection-panel-subtitle"),
                html.Div(str(exc), className="inspection-note-box inspection-note-box--danger"),
            ],
            className="inspection-ai-report-card",
        )
