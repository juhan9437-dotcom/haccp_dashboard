$ErrorActionPreference = "Stop"

if (-not (Test-Path ".venv312\\Scripts\\python.exe")) {
    throw "대시보드 venv(.venv312)가 없습니다. 먼저 scripts\\setup_dashboard_env.ps1 를 실행하세요."
}

$env:PYTHONDONTWRITEBYTECODE = "1"
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"

if (-not $env:HACCP_API_BASE_URL) {
    $env:HACCP_API_BASE_URL = "http://127.0.0.1:5000"
}

if (-not $env:HACCP_ENABLE_EMBEDDED_BRIDGE) {
    $env:HACCP_ENABLE_EMBEDDED_BRIDGE = "0"
}

& .\.venv312\Scripts\python haccp_dashboard\app.py
