from dash import dcc, html

MILK_QUALITY_MOCK_BATCHES = {
    1: {
        "batch_name": "BATCH-001",
        "line_label": "QC A",
        "status": "정상",
        "focus": "품질 양호",
        "summary": "우유 품질 정상",
        "indicators": ["산도 정상", "pH 6.8", "순도 99.2%"],
        "counts": [27, 26, 27, 26, 27, 26, 27],
    },
    54: {
        "batch_name": "BATCH-054",
        "line_label": "QC B",
        "status": "경고",
        "focus": "주의 필요",
        "summary": "품질 모니터링 중",
        "indicators": ["산도 높음", "pH 주의", "순도 96.5%"],
        "counts": [21, 24, 23, 25, 24, 26, 25],
    },
    112: {
        "batch_name": "BATCH-112",
        "line_label": "QC C",
        "status": "위험",
        "focus": "긴급 처리",
        "summary": "품질 부적합",
        "indicators": ["미생물 검출", "산도 높음", "순도 62.1%"],
        "counts": [18, 19, 20, 19, 20, 21, 20],
    },
}
pd.read_csv(), load_model(),

def get_milk_quality_batch_ids():
    return list(MILK_QUALITY_MOCK_BATCHES.keys())


def build_milk_quality_figure(batch_id: int):
    import plotly.graph_objects as go  # type: ignore

    batch = MILK_QUALITY_MOCK_BATCHES[int(batch_id)]
    x_values = list(range(1, len(batch["counts"]) + 1))
    y_values = batch["counts"]

    figure = go.Figure()
    figure.add_trace(
        go.Scatter(
            x=x_values,
            y=y_values,
            mode="lines+markers+text",
            text=[str(value) for value in y_values],
            textposition="top center",
            line=dict(color="#c8846d", width=4, shape="spline"),
            marker=dict(size=11, color="#c8846d", line=dict(color="white", width=2)),
            fill="tozeroy",
            fillcolor="rgba(200, 132, 109, 0.16)",
            hovertemplate="데이 %{x}번<br>입수 %{y}건<extra></extra>",
        )
    )
    figure.update_layout(
        margin=dict(l=54, r=24, t=24, b=48),
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
        xaxis=dict(
            title="검사 순번",
            tickmode="array",
            tickvals=x_values,
            showgrid=True,
            gridcolor="rgba(205, 186, 166, 0.24)",
            zeroline=False,
        ),
        yaxis=dict(
            title="합격 입수 건수",
            showgrid=True,
            gridcolor="rgba(205, 186, 166, 0.24)",
            zeroline=False,
        ),
        showlegend=False,
    )
    return figure


def build_milk_quality_batch_button(batch_id: int, is_active: bool = False):
    batch = MILK_QUALITY_MOCK_BATCHES[int(batch_id)]
    status_class = "danger" if batch["status"] == "위험" else "warning"
    class_name = "batch-preview-button active" if is_active else "batch-preview-button"

    return html.Button(
        [
            html.Div(
                [
                    html.Div(batch["line_label"], className="preview-chip"),
                    html.Div(batch["status"], className=f"preview-status {status_class}"),
                ],
                className="preview-top",
            ),
            html.Div(
                [
                    html.Div(className="qc-floor"),
                    html.Div(className="qc-path qc-path-1"),
                    html.Div(className="qc-path qc-path-2"),
                    html.Div(className="qc-unit qc-sampler"),
                    html.Div(className="qc-unit qc-lab"),
                    html.Div(className="qc-unit qc-tank"),
                    html.Div(className="qc-unit qc-droplet"),
                    html.Div(batch["focus"], className="qc-callout"),
                    html.Div(className="preview-glow"),
                ],
                className="preview-hero preview-hero-qc",
            ),
            html.Div(batch["batch_name"], className="preview-title"),
            html.Div(batch["summary"], className="preview-caption", style={"fontSize": "12px", "minHeight": "32px"}),
            html.Div([html.Span(item, className="preview-meta-pill") for item in batch["indicators"]], className="preview-meta"),
        ],
        id={"type": "main-batch-button", "index": batch_id},
        n_clicks=0,
        className=class_name,
    )


def build_milk_quality_section():
    default_batch_id = get_milk_quality_batch_ids()[0]
    return html.Div(
        [
            html.Div(
                [
                    html.H2("우유 품질 현황", style={"marginBottom": "18px", "fontSize": "24px", "fontWeight": "700", "color": "#1a202c"}),
                    html.P("각 배치별로 수집된 우유 품질 분석 내용, 검사 결과, 최종 출하 적합성을 확인합니다.", className="main-chart-description"),
                    html.Div(
                        [
                            build_milk_quality_batch_button(batch_id, is_active=index == 0)
                            for index, batch_id in enumerate(get_milk_quality_batch_ids())
                        ],
                        id="main-batch-selector",
                        className="batch-preview-strip",
                    ),
                ],
                className="main-insight-panel",
            ),
            html.Div(
                [
                    html.Div(
                        [
                            html.H2("품질 지표 분석", style={"marginBottom": "6px", "fontSize": "24px", "fontWeight": "700", "color": "#1a202c"}),
                            html.P("미생물오염도와 산도 지표를 시간별로 추적하여 품질 변화, 편차 발생, 최종 판정을 파악합니다.", className="main-chart-description"),
                        ]
                    ),
                    dcc.Graph(
                        id="main-batch-inspection-graph",
                        figure=build_milk_quality_figure(default_batch_id),
                        config={"displayModeBar": False},
                        className="main-batch-graph",
                    ),
                ],
                className="main-insight-panel",
            ),
        ],
        className="main-insight-grid",
    )
