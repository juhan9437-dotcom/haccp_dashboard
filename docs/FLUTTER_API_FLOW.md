## Flutter API Flow

### 기본 원칙

- Flutter는 Dash에 직접 붙지 않고 Flask bridge만 호출합니다.
- 실시간 상태 수신은 SSE를 기본으로 사용합니다.
- API 인증은 `X-API-Key` 헤더 기준입니다.

### 권장 호출 순서

1. 앱 시작
- `GET /api/model-status`
- 모델 로드 상태와 bridge 가용성을 먼저 확인합니다.

2. 센서 실시간 구독
- `GET /api/dashboard-stream`
- 내부망 또는 `stream_token`이 있는 경우 SSE로 센서/알람/runtime 상태를 함께 수신합니다.

3. 센서 이벤트 저장
- `POST /api/ingest/sensor`
- 공정 센서 스냅샷을 bridge에 저장합니다.

4. 이미지 업로드
- `POST /api/ingest/image`
- 최종검사 이미지를 업로드하고 저장된 이미지 메타를 받습니다.

5. 이미지 판독 필요 시
- `POST /api/infer/image`
- 업로드 직후 또는 재판독 요청 시 사용합니다.

6. 보고서 저장
- `POST /api/reports`
- Flutter 화면에서 확정한 판정/메모/첨부 이미지를 저장합니다.

7. 이력 조회
- `GET /api/reports`
- 저장된 보고서 목록을 다시 조회합니다.

8. 원본 이미지 보기
- `GET /api/images/<image_id>/file`
- 업로드 원본을 재조회합니다.

### 실시간 경로 선택

- 기본 선택: SSE
- 이유: HTTP 기반이라 프록시 구성과 장애 분석이 단순하고, Dash 브라우저와 Flutter 모두 같은 bridge endpoint를 공유하기 쉽습니다.
- Socket.IO는 양방향 제어가 꼭 필요할 때만 선택 옵션으로 둡니다.

### 운영 메모

- Dash는 `HACCP_API_BASE_URL`을 bridge 주소로 설정합니다.
- 브라우저 SSE가 다른 포트의 bridge로 붙는 경우 `HACCP_CORS_ALLOW_ORIGIN`을 함께 설정합니다.
- 개발 중에는 `scripts/run_bridge.ps1`와 `scripts/run_dashboard.ps1`를 각각 실행합니다.