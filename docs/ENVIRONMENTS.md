## 가상환경 분리(.venv312 / .venv_feat312)

이 프로젝트는 **대시보드 실행 환경**과 **이미지 feature 추출(CNN/handcrafted) 환경**을 완전히 분리합니다(의존성 충돌 방지).

### 1) 대시보드용: `.venv312`
- 용도: Dash 대시보드 실행 + standalone Flask bridge 실행 + DB(sqlite) 저장/조회
- 설치: `haccp_dashboard/requirements.txt`

```powershell
.\scripts\setup_dashboard_env.ps1
.\scripts\run_dashboard.ps1
.\scripts\run_bridge.ps1
```

### 2) feature 추출용: `.venv_feat312`
- 용도: `haccp_dashboard/feature_extraction.py` 실행(이미지에서 특징값 추출)
- 설치:
  - handcrafted: `haccp_dashboard/requirements_feature_extraction.txt`
  - CNN intermediate/fusion_ready: `haccp_dashboard/requirements_feature_extraction_cnn.txt`

```powershell
.\scripts\setup_feature_env.ps1
.\scripts\run_feature_extraction.ps1 -Mode handcrafted -DataDir "haccp_dashboard\\resize_640 x 360" -Output "haccp_dashboard\\_tmp_hand.csv"
.\scripts\run_feature_extraction.ps1 -Mode cnn_intermediate -DataDir "haccp_dashboard\\resize_640 x 360" -Output "haccp_dashboard\\_tmp_cnn.csv"
```

### 공통 참고
- 두 환경을 섞어서 `pip install` 하지 마세요.
- `.venv312`에는 `torch/opencv/scikit-image`를 넣지 않는 것을 권장합니다.
- DB 저장 경로는 `HACCP_DB_PATH`, 데이터 폴더는 `HACCP_DATA_DIR`로 변경할 수 있습니다(대시보드 서버 기준).
- bridge를 분리해서 쓸 때는 Dash 쪽에 `HACCP_API_BASE_URL=http://127.0.0.1:5000` 같은 형태로 bridge 주소를 지정합니다.

