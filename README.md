# HACCP Dashboard

매일유업 우유 공정관리 모니터링 대시보드 (Dash 기반).

## 주요 기능
- QC/QA 메인 대시보드 (라인별 실시간 CCP 상태)
- 가열 살균 공정 모니터링
- 최종 품질 검사
- 알람 이력 관리
- AI 도우미 (사이드 패널)

## 폴더 구조
```
haccp_dashboard/
├── app.py              # Dash 엔트리포인트
├── api_routes.py       # 외부 API 엔드포인트
├── bridge_server.py    # 센서 브릿지
├── pages/              # 멀티페이지 레이아웃
├── lib/                # 헬퍼/도메인 로직
├── components/         # 공용 컴포넌트
├── models/             # 추론 코드 (가중치는 별도 배포)
├── utils/              # 상태/로직 유틸
├── assets/             # CSS/이미지/SVG
└── CNN 파일/            # 모델 설정 JSON
control_tower_app/      # 보조 앱
docs/                   # 명세 문서
scripts/                # 실행 PowerShell 스크립트
```

## 실행 방법

### 1) 가상환경
```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r haccp_dashboard\requirements.txt
```

### 2) 환경변수
`haccp_dashboard\.env.example`을 `.env`로 복사 후 값 채우기.

### 3) 모델 가중치
`*.pt`, `*.pth`, `*.keras` 파일은 용량 문제로 저장소에 포함되지 않습니다.
별도 배포본을 받아 다음 위치에 배치:
- `haccp_dashboard/CNN 파일/mobilenetv2_final_full.pt`
- `haccp_dashboard/CNN 파일/mobilenetv2_final.pth`
- `haccp_dashboard/models/track1_inception_fold5.keras`
- `haccp_dashboard/models/track2_inception_fold5.keras`

### 4) 실행
```powershell
.\scripts\run_dashboard.ps1
```
또는
```powershell
python haccp_dashboard\app.py
```
http://127.0.0.1:8050 접속.

## 문서
- [docs/PROCESS_SPEC.md](docs/PROCESS_SPEC.md) — 공정 사양
- [docs/DATAFLOW.md](docs/DATAFLOW.md) — 데이터 흐름
- [docs/ENVIRONMENTS.md](docs/ENVIRONMENTS.md) — 환경 설정
- [docs/FLUTTER_API_FLOW.md](docs/FLUTTER_API_FLOW.md) — Flutter 연동

## 기술 스택
- Python 3.12, Dash, Flask, Plotly, Bootstrap
- PyTorch, TensorFlow/Keras, scikit-learn
- SQLite (로컬 운영 DB)

## 라이선스
내부 프로젝트용. 외부 배포 전 라이선스 정책 확인 필요.
