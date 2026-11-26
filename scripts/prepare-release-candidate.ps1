param(
    [Parameter(Mandatory)][string]$PreviousVersion,
    [Parameter(Mandatory)][int]$PreviousAndroidCode,
    [string]$Gitleaks = 'gitleaks.exe',
    [switch]$Offline,
    [switch]$AllowUnsignedWindows
)
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $root
$sourceStatus = & git status --porcelain
if ($LASTEXITCODE -ne 0 -or $sourceStatus) {
    throw 'Prepare release assets from a clean checkout of the reviewed Git commit.'
}
$version = (Get-Content -LiteralPath 'release-version.json' -Raw | ConvertFrom-Json).version
$python = Join-Path $root '.venv/Scripts/python.exe'
$vault = Join-Path $PSScriptRoot 'release-vault.py'
$work = Join-Path $root "local/release-builds/$version"
if (Test-Path -LiteralPath $work) { throw "Release staging already exists: $work" }
New-Item -ItemType Directory -Path $work | Out-Null
if (-not $env:ANDROID_HOME) { $env:ANDROID_HOME = Join-Path $env:LOCALAPPDATA 'Android/Sdk' }
if (!$env:GRADLE_USER_HOME -and (Test-Path -LiteralPath 'local/android-gradle')) {
    $env:GRADLE_USER_HOME = (Resolve-Path -LiteralPath 'local/android-gradle').Path
}
function Assert-Passed([string]$phase) {
    if ($LASTEXITCODE -ne 0) { throw "$phase failed (exit $LASTEXITCODE)" }
}

& $Gitleaks git --log-opts='--all' --redact=100 --no-banner --gitleaks-ignore-path '.gitleaksignore' .
Assert-Passed 'Repository history secret scan'
& npm.cmd run check
Assert-Passed 'Required Windows and Python checks'
& npx.cmd playwright test tests/desktop/distribution.spec.ts --workers=1
Assert-Passed 'Distribution interface'
$androidChecks = @('-Release', '-Check')
if ($Offline) { $androidChecks += '-Offline' ; $env:UV_OFFLINE = '1' }
& $python scripts/prepare-android-camplus.py
Assert-Passed 'Pinned public CAM++ model'
& $python $vault run android -- pwsh.exe -NoProfile -File scripts/build-android.ps1 @androidChecks
Assert-Passed 'Signed Android APK and lint'
$winOptions = @("--config.directories.output=$work")
if (-not $AllowUnsignedWindows) { $winOptions += @('--config.win.signExecutable=true', '--config.forceCodeSigning=true') }
& $python $vault run public -- npm.cmd run package:win -- @winOptions
Assert-Passed 'Windows NSIS package'
& node scripts/test-packaged.mjs (Join-Path $work 'win-unpacked/WileyAI.exe')
Assert-Passed 'Packaged Windows smoke test'
$apk = Join-Path $work "WileyAI-Android-$version-release.apk"
Copy-Item -LiteralPath 'android/app/build/outputs/apk/release/app-release.apk' -Destination $apk
$setup = Join-Path $work "WileyAI-Setup-$version-x64.exe"
& $python scripts/audit-release-assets.py --android $apk --windows-dir (Join-Path $work 'win-unpacked')
Assert-Passed 'Public artifact inventory and licenses'
$output = Join-Path $work 'candidate'
$manifestArgs = @('--tag', "v$version", '--previous-version', $PreviousVersion, '--previous-android-code',
    "$PreviousAndroidCode", '--notes', "docs/releases/$version.ru.md", '--windows', $setup, '--android', $apk,
    '--android-tools', (Join-Path $env:ANDROID_HOME 'build-tools/36.0.0'), '--output', $output)
if ($AllowUnsignedWindows) { $manifestArgs += '--allow-unsigned-windows' }
& $python $vault run manifest -- $python scripts/prepare-update-release.py @manifestArgs
Assert-Passed 'Release manifest signing'
& $python scripts/verify-release-download.py --tag "v$version" --manifest (Join-Path $output 'wiley-update-v2.json') $setup $apk
Assert-Passed 'Independent verification with public trust pin'
Write-Output "Local candidate: $output"
