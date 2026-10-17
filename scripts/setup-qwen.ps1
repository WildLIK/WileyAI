param([ValidateSet("cu128", "cpu")][string]$Backend = "cu128")
$ErrorActionPreference = "Stop"
$projectDir = Split-Path -Parent $PSScriptRoot
Push-Location -LiteralPath $projectDir
try {
    uv venv local/qwen-tts/.venv --python 3.12 --allow-existing
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    uv pip install --python local/qwen-tts/.venv/Scripts/python.exe --torch-backend $Backend "torch==2.9.1" "torchaudio==2.9.1" "qwen-tts==0.1.1" "huggingface-hub<1"
    exit $LASTEXITCODE
} finally {
    Pop-Location
}
