import base64
import io

import pandas as pd
from dash import html

from .main_helpers import get_openai_chat_model, get_openai_client, get_openai_timeout_seconds


def _lazy_models():
    # Defer heavy TF model imports until the user actually triggers CSV inference.
    from haccp_dashboard.models import get_inference_status, predict_contamination
    return get_inference_status, predict_contamination

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



def build_csv_upload_status_panel(upload_data=None, error_message=None):
    get_inference_status, _ = _lazy_models()
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



def build_csv_inference_idle_panel():
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
        f"2차 분류 임계값은 {prediction['threshold']:.2f}이며 현재 점수는 {prediction['track2_score']:.3f}입니다."
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



def _build_inference_error_panel(error_message):
    return html.Div(
        [
            html.Div("AI 오염 유사도 분석", className="inspection-panel-title"),
            html.Div("추론 중 오류가 발생했습니다.", className="inspection-panel-subtitle"),
            html.Div(str(error_message), className="inspection-note-box inspection-note-box--danger"),
        ],
        className="inspection-ai-report-card",
    )



def _decode_csv_upload(contents):
    if not contents:
        raise ValueError("CSV 파일이 업로드되지 않았습니다.")

    _, content_string = contents.split(",", 1)
    decoded = base64.b64decode(content_string)
    return pd.read_csv(io.StringIO(decoded.decode("utf-8-sig")))



def resolve_csv_upload_state(contents, filename):
    if not contents:
        return (
            None,
            html.Div(
                [
                    html.Div("CSV 업로드", className="inspection-upload-drop-title"),
                    html.Div("센서 시계열 CSV를 드래그하거나 클릭해 선택합니다.", className="inspection-upload-drop-copy"),
                ]
            ),
            build_csv_upload_status_panel(),
            True,
        )

    try:
        dataframe = _decode_csv_upload(contents)
        payload = {
            "filename": filename or "uploaded.csv",
            "rows": int(len(dataframe)),
            "columns": list(dataframe.columns),
            "data": dataframe.to_json(date_format="iso", orient="split"),
        }
        upload_children = html.Div(
            [
                html.Div("업로드 완료", className="inspection-upload-drop-title"),
                html.Div(f"{payload['filename']} · {payload['rows']:,}행", className="inspection-upload-drop-copy"),
            ]
        )
        return payload, upload_children, build_csv_upload_status_panel(upload_data=payload), False
    except Exception as exc:
        return (
            None,
            html.Div(
                [
                    html.Div("업로드 실패", className="inspection-upload-drop-title"),
                    html.Div(str(exc), className="inspection-upload-drop-copy"),
                ]
            ),
            build_csv_upload_status_panel(error_message=str(exc)),
            True,
        )



def resolve_csv_inference_result(n_clicks, upload_data):
    if not upload_data or not n_clicks:
        return build_csv_inference_idle_panel()

    _, predict_contamination = _lazy_models()
    try:
        raw_df = pd.read_json(io.StringIO(upload_data["data"]), orient="split")
        result = predict_contamination(raw_df)
        summary_payload = _build_openai_inference_summary(result)
        return _build_inference_result_panel(result, summary_payload)
    except Exception as exc:
        return _build_inference_error_panel(exc)
