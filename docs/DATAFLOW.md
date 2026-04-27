## 데이터 연결 구조(Flask Bridge ↔ Dashboard ↔ Flutter)

권장 구성은 **Flask bridge 서버를 Dash와 분리**해서 운영하는 방식입니다.

- Flask bridge: 원본/전처리 데이터 저장, Flutter 연동, SSE 제공
- Dash dashboard: 모델 추론, 시각화, bridge API 조회
- 개발 편의용으로만 `HACCP_ENABLE_EMBEDDED_BRIDGE=1`일 때 Dash 내부에 API blueprint를 같이 붙일 수 있습니다.

### 저장(Flask bridge 역할)
- 센서 이벤트 저장: `POST /api/ingest/sensor` → `haccp_dashboard/db_store.py` → sqlite(`haccp_dashboard/data/haccp.sqlite3`)
- 이미지 원본 저장: `POST /api/ingest/image`(multipart) → 업로드 파일 저장(`haccp_dashboard/data/uploads/`) + 메타 sqlite 기록
- 보고서/사진 메타 저장(Flutter): `POST /api/reports` → sqlite 기록

### 조회(Dash 역할)
- 최신 센서 조회: `GET /api/sensor-data` (DB 우선, 없으면 CSV demo fallback)
- 알람 조회: `GET /api/alerts`
- 업로드 이미지 원본 다운로드: `GET /api/images/<image_id>/file`
- 보고서 목록: `GET /api/reports`

### 실시간(권장)
- 기본 경로는 SSE: `GET /api/dashboard-stream`
- 이유: Dash 브라우저 구독과 Flutter bridge 연동에서 구현 단순성, 재연결 안정성, 운영 추적성이 가장 좋습니다.
- Socket.IO는 선택 기능으로만 유지합니다. `HACCP_ENABLE_SOCKETIO=1`일 때 이벤트 emit (`sensor_event`, `image_event`, `report_event`)

### 실행 방식
- Dash: `scripts/run_dashboard.ps1`
- Standalone bridge: `scripts/run_bridge.ps1`
- Dash는 `HACCP_API_BASE_URL`을 bridge 주소로 설정하고, 브라우저 SSE도 같은 주소를 사용합니다.

## 메인 카드 기준 분리

- 센서 기반 수치: 센서 시계열 경고/위험 임계치 기준으로 집계합니다.
- 최종검사 기반 수치: 이미지/최종검사 판정 기준으로 정상/경고/위험을 집계합니다.
- 메인 페이지의 대표 배치 3개는 날짜별 **리스크 상위 시간구간 배치(2시간 로트)** 기준으로 고정합니다.

## 최종검사 1200장 규칙 검증

- 실제 이미지 데이터셋(`resize_640 x 360`)을 기준으로 검증합니다.
- 현재 저장 수량은 총 6,000장이고, `5일 x 1,200장` 규칙과 일치합니다.
- 클래스 분포는 `pure_milk 2,000장`, `water_mixed 2,000장`, `glucose_mixed 2,000장`입니다.
- 따라서 현재는 1200/day 규칙을 유지하되, 일일 비율은 실데이터 분포를 바탕으로 결정적 변동만 주는 방식으로 사용합니다.

## 공정 단계 / 일일 공정 횟수 기준

- 운영 상태의 기본 단위는 **시간 기반 배치(time-based lot)** 입니다.
- 배치 정의: 연속 공정이지만 분석/추적을 위해 **2시간 단위 시간 구간**을 1개 배치로 정의합니다.
- 일일 운영: 하루 **20시간 가동**, 라인 기준 **2시간 × 10개 로트(=10배치)** 가 시간 순서대로 생성됩니다.
- 전체 배치: `3개 라인 × 10배치/일/라인 × 5일 = 150배치`

- 공정 단계(각 배치는 아래 단계를 **단 1회만** 순차 통과):
  `원유입고 → 저장 → 여과 → 표준화 → 가열 → 보온 → 냉각 → 충진 → 검사 → 출하판정`

- 설계 원칙
  - 공정은 연속적으로 흐르되, 배치는 시간 구간으로 끊어 정의합니다.
  - "공정 반복 = 배치 반복"으로 설명하지 않습니다.

---

## 데이터 로딩 콜체인(페이지별) + 중복 로딩 최소화

본 프로젝트는 모든 페이지가 아래 **공통 데이터 소스**를 기준으로 동작합니다.

- 센서(공정) CSV: `C:\haccp_dashboard\haccp_dashboard\batch_150_contaminated_onlylabel_final_v4.csv`
- 이미지 데이터셋 폴더: `C:\haccp_dashboard\haccp_dashboard\resize_640 x 360`

### 페이지 라우팅(빈 화면 방지)

Dash Pages(`dash.page_container`)는 초기 로딩 시점에 `_pages_content.children`가 비어있는 상태로 시작하는 경우가 있어,
메인 콘텐츠가 “빈 화면”처럼 보일 수 있습니다.

- `haccp_dashboard/app.py:render_page_content`
  - `dcc.Location(id="url")`의 `pathname/search`를 입력으로 받아
  - `dash.page_registry[path].layout()`을 즉시 렌더링하여 `page-content`에 주입합니다.

즉, `/`(메인) 진입 시에도 페이지 레이아웃이 바로 표시되고, 이후 각 페이지의 콜백이 실시간으로 갱신합니다.

### 공통(전역) 실시간 센서 캐시(`sensor-cache`)

- `haccp_dashboard/app.py:ingest_runtime_event`
  - → `haccp_dashboard/lib/main_helpers.py:get_sensor_data`
    - (원격) `requests.get({HACCP_API_BASE_URL}/api/sensor-data)` 성공 시: 응답 JSON → `sensor-cache` 저장
    - (폴백) 원격 실패 시:
      - → `haccp_dashboard/lib/dashboard_demo.py:_load_process_dataframe`
        - → `haccp_dashboard/lib/main_helpers.py:load_process_batch_dataframe`
          - → `haccp_dashboard/lib/main_helpers.py:_load_process_batch_dataframe_cached`
            - → `pandas.read_csv(공통 센서 CSV)`

즉, 페이지들은 “직접 CSV를 매번 읽는 방식”이 아니라, 전역 `sensor-cache`(3분 폴링)를 우선 사용합니다.

---

### 메인 페이지(`/`) — `haccp_dashboard/pages/main.py`

1) KPI(상단 카드)

- `render_main_kpis`
  - → `haccp_dashboard/lib/main_helpers.py:load_heating_dataset(os.path.dirname(__file__))`
    - → `resolve_process_csv_path`
      - → `load_process_batch_dataframe`
        - → `_load_process_batch_dataframe_cached`
          - → `pandas.read_csv(공통 센서 CSV)`

2) 라인별 “즉시 조치 Batch 현황”(카드)

- 기본은 전역 `sensor-cache`를 그대로 사용(추가 CSV 로딩 없음)
- `sensor-cache`가 비어있을 때만:
  - → `load_heating_dataset(os.path.dirname(__file__))`로 로컬 CSV 기반 fallback snapshot 구성

3) 라인별 실시간 “부적합 비율 비교”(Bar)

- `render_line_defect_rate_chart`
  - → `haccp_dashboard/lib/dashboard_demo.py:get_final_product_batch_summary_frame`
    - → `get_final_inspection_summary_frame`
      - → `_build_final_inspection_dataset_frame`
        - → `get_batch_summary_frame`
          - → `_load_process_dataframe` → (결국) `pandas.read_csv(공통 센서 CSV)` (캐시 1회)
      - → `get_final_inspection_dataset_profile`
        - → `_resolve_final_inspection_dataset_dir`(기본: 공통 이미지 폴더)
          - → `os.walk(공통 이미지 폴더)`로 클래스별 이미지 개수 집계(캐시 1회)

---

### 가열 페이지(`/heating`) — `haccp_dashboard/pages/heating.py`

1) 배치 상세 시계열(그래프/표)

- `_batch_frame(batch_id)`
  - → `haccp_dashboard/lib/main_helpers.py:load_heating_dataset(os.path.dirname(__file__))`
    - → (캐시 경유) `pandas.read_csv(공통 센서 CSV)`

2) 배치 요약/리스크 목록

- `dashboard_demo.get_batch_summary_frame` / `get_hidden_anomaly_batch_items`
  - → `_load_process_dataframe` → (캐시 경유) `pandas.read_csv(공통 센서 CSV)`

---

### 최종검사 페이지(`/final-inspection`) — `haccp_dashboard/pages/final_inspection.py`

1) 최종검사 기록(하단 테이블) / 배치 판정 요약

- `_inspection_record_rows` / `demo.get_final_inspection_rows`
  - → `_filter_final_inspection_summary`
    - → `get_final_inspection_summary_frame`
      - → `get_final_inspection_dataset_profile`
        - → `os.walk(공통 이미지 폴더)`로 클래스별 이미지 개수 집계(캐시 1회)
      - → `_build_final_inspection_dataset_frame`
        - → `get_batch_summary_frame` → (캐시 경유) `pandas.read_csv(공통 센서 CSV)`

2) 업로드 기반 AI 추론(CSV/이미지 업로드)

- CSV 업로드 추론:
  - 업로드된 CSV bytes를 `pandas.read_csv(StringIO(...))`로 읽어 **모델 추론 입력**으로만 사용
  - 공통 센서 CSV를 다시 읽지 않음
- 이미지 업로드 추론:
  - 업로드된 이미지 bytes를 CNN 모델로 추론
  - 공통 이미지 폴더를 다시 읽지 않음(폴더는 “데이터셋 프로필 집계/학습” 용도)

---

### 중복 로딩을 줄이기 위해 적용한 리팩토링

- 페이지에서 `dashboard_demo._load_process_dataframe()` 직접 호출을 줄이고,
  가능한 곳은 `haccp_dashboard/lib/main_helpers.py:load_heating_dataset(os.path.dirname(__file__))`로 통일했습니다.
- CSV 실파일 읽기(`pandas.read_csv`)는 `haccp_dashboard/lib/main_helpers.py:_load_process_batch_dataframe_cached` 한 곳에서만 발생하도록 유지합니다.
- 이미지 폴더 스캔(`os.walk`)은 `get_final_inspection_dataset_profile`에서 `lru_cache(maxsize=1)`로 1회만 수행합니다.
