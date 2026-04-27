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

### 3) 데이터셋 / 모델 가중치 다운로드

대용량 데이터셋(이미지) 및 모델 가중치(`*.pt`, `*.keras`)는 저장소에 포함되지 않으며, **GitHub Release**에서 별도로 배포합니다.

- 다운로드: [haccp_dashboard_release_v1.zip](https://github.com/juhan9437-dotcom/haccp_dashboard/releases/download/v1.0/haccp_dashboard_release_v1.zip) (약 173 MB)
- Release 페이지: https://github.com/juhan9437-dotcom/haccp_dashboard/releases/tag/v1.0

**zip 내용**
| 경로 | 설명 |
|---|---|
| `csv/batch_150_contaminated_onlylabel_final_v4.csv` | 메인 학습/추론 CSV |
| `csv/sample_inference_input_19f.csv` | 추론 샘플 입력 |
| `models/cnn/mobilenetv2_final_full.pt` (+ JSON 3종) | MobileNetV2 이미지 모델 |
| `models/sensor/track1_inception_fold5.keras` | 센서 track1 모델 |
| `models/sensor/track2_inception_fold5.keras` | 센서 track2 모델 |
| `images/{pure_milk,water_mixed,glucose_mixed}/` | 이미지 샘플 1000장 (비율 0.7 / 0.2 / 0.1) |

**압축 해제 후 배치 위치**
```
csv/*.csv                            →  haccp_dashboard/
models/cnn/*                         →  haccp_dashboard/CNN 파일/
models/sensor/*.keras                →  haccp_dashboard/models/
images/<class>/*.png                 →  haccp_dashboard/resize_640 x 360/<class>/
```

> 전체 이미지(6000장, 약 810 MB)가 필요한 경우 별도 문의하세요. Release zip 은 학습/추론 검증에 충분한 1000장만 포함합니다.

데이터셋 재생성:
```powershell
python scripts\export_dataset.py --total 1000 --clean
```

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
