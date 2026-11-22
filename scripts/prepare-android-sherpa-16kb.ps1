$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$dest = Join-Path $root 'local\android-libs\sherpa-onnx-1.13.5.aar'
$expected = '6419CD8BC983E0C4FAB06067F0FE0313FDC0F7103818AC1E7A08D50787B7A82B'
if (Test-Path -LiteralPath $dest) {
    if ((Get-FileHash -LiteralPath $dest -Algorithm SHA256).Hash -ne $expected) { throw 'Existing AAR has an unexpected hash; it was not replaced.' }
    Write-Host 'Verified sherpa-onnx 1.13.5 is already available.'
    return
}
New-Item -ItemType Directory -Force -Path (Split-Path -Parent $dest) | Out-Null
$tmp = Join-Path (Split-Path -Parent $dest) ('sherpa-download-' + [guid]::NewGuid().ToString('N') + '.tmp')
try {
    Invoke-WebRequest -Uri 'https://github.com/k2-fsa/sherpa-onnx/releases/download/v1.13.5/sherpa-onnx-1.13.5.aar' -OutFile $tmp
    if ((Get-FileHash -LiteralPath $tmp -Algorithm SHA256).Hash -ne $expected) { throw 'AAR hash mismatch.' }
    Move-Item -LiteralPath $tmp -Destination $dest
} finally { if (Test-Path -LiteralPath $tmp) { Remove-Item -LiteralPath $tmp } }
