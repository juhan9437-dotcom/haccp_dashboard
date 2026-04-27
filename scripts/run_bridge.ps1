$ErrorActionPreference = "Stop"

if (-not (Test-Path ".venv312\Scripts\python.exe")) {
    throw "대시보드 venv(.venv312)가 없습니다. 먼저 scripts\setup_dashboard_env.ps1 를 실행하세요."
}

$env:PYTHONDONTWRITEBYTECODE = "1"
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"
& .\.venv312\Scripts\python haccp_dashboard\bridge_server.py