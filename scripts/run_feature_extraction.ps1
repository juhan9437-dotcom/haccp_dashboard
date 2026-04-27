param(
    [ValidateSet("handcrafted", "cnn_intermediate", "cnn_fusion_ready")]
    [string]$Mode = "handcrafted",
    [string]$DataDir = "haccp_dashboard\\resize_640 x 360",
    [string]$Output = "haccp_dashboard\\_tmp_hand.csv",
    [string]$Device = $(if ($env:HACCP_IMAGE_DEVICE) { $env:HACCP_IMAGE_DEVICE } else { "cpu" }),
    [ValidateSet("float16", "float32")]
    [string]$Dtype = "float16"
)

$ErrorActionPreference = "Stop"

if (-not (Test-Path ".venv_feat312\\Scripts\\python.exe")) {
    throw "feature venv(.venv_feat312)가 없습니다. 먼저 scripts\\setup_feature_env.ps1 를 실행하세요."
}

$env:PYTHONDONTWRITEBYTECODE = "1"
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"
& .\.venv_feat312\Scripts\python haccp_dashboard\feature_extraction.py `
    --mode $Mode `
    --data_dir $DataDir `
    --output $Output `
    --device $Device `
    --dtype $Dtype
