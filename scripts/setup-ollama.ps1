param([string]$Version = 'v0.40.4')
$ErrorActionPreference = 'Stop'
$taskRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$taskRuntime = Join-Path $taskRoot 'local\ollama'
$taskArchive = Join-Path $taskRoot 'local\ollama-windows-amd64.zip'
New-Item -ItemType Directory -Path $taskRuntime -Force | Out-Null
if (Test-Path -LiteralPath (Join-Path $taskRuntime 'ollama.exe')) {
    Write-Output 'Portable Ollama already exists.'
    exit 0
}
$taskUrl = "https://github.com/ollama/ollama/releases/download/$Version/ollama-windows-amd64.zip"
Write-Output "Downloading official Ollama $Version (approximately 1.5 GB)..."
& curl.exe --fail --location --retry 2 --silent --show-error --output $taskArchive $taskUrl
if ($LASTEXITCODE -ne 0) { throw 'Ollama download failed' }
$taskSums = Join-Path $taskRoot 'local\ollama-sha256sum.txt'
& curl.exe --fail --location --retry 2 --silent --show-error --output $taskSums "https://github.com/ollama/ollama/releases/download/$Version/sha256sum.txt"
if ($LASTEXITCODE -ne 0) { throw 'Could not download official checksums' }
$taskChecksumLine = Get-Content -LiteralPath $taskSums | Where-Object {$_ -match '\s+(\./)?ollama-windows-amd64\.zip$'} | Select-Object -First 1
if (-not $taskChecksumLine) { throw 'Checksum for Windows archive not found' }
$taskExpectedHash = ($taskChecksumLine -split '\s+')[0]
if ((Get-FileHash -LiteralPath $taskArchive -Algorithm SHA256).Hash -ne $taskExpectedHash) { throw 'Archive checksum mismatch' }
Write-Output 'Extracting portable runtime...'
Expand-Archive -LiteralPath $taskArchive -DestinationPath $taskRuntime -Force
Write-Output 'Portable runtime ready. No system service or PATH changes were made.'
