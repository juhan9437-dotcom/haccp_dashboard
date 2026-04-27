param(
    [switch]$WithCnn,
    [string]$Python = "py",
    [string]$Version = "3.12"
)

$ErrorActionPreference = "Stop"

function Get-Python312Args {
    param([string]$Python, [string]$Version)
    if ($Python -eq "py" -and (Get-Command py -ErrorAction SilentlyContinue)) {
        return @("py", "-$Version")
    }
    if (Get-Command $Python -ErrorAction SilentlyContinue) {
        return @($Python)
    }
    if (Get-Command python -ErrorAction SilentlyContinue) {
        return @("python")
    }
    throw "Python 실행 파일을 찾지 못했습니다. `-Python` 파라미터로 python 경로를 지정하세요."
}

$cmd = Get-Python312Args -Python $Python -Version $Version

if (-not (Test-Path ".venv_feat312")) {
    if ($cmd.Length -gt 1) {
        & $cmd[0] $cmd[1] -m venv .venv_feat312
    }
    else {
        & $cmd[0] -m venv .venv_feat312
    }
}

& .\.venv_feat312\Scripts\python -m pip install --upgrade pip
& .\.venv_feat312\Scripts\pip install -r haccp_dashboard\requirements_feature_extraction.txt

if ($WithCnn) {
    & .\.venv_feat312\Scripts\pip install -r haccp_dashboard\requirements_feature_extraction_cnn.txt
}

Write-Host "OK: feature venv ready (.venv_feat312)"
