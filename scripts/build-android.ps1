param([switch]$Offline)
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
if (-not $env:JAVA_HOME) { throw 'Set JAVA_HOME to JDK 17.' }
if (-not $env:ANDROID_HOME) { $env:ANDROID_HOME = Join-Path $env:LOCALAPPDATA 'Android\Sdk' }
if (-not (Test-Path -LiteralPath $env:ANDROID_HOME)) { throw 'Set ANDROID_HOME to the Android SDK.' }
$keytool = Join-Path $env:JAVA_HOME 'bin\keytool.exe'
if (-not (Test-Path -LiteralPath $keytool)) { throw 'keytool was not found in JAVA_HOME.' }
$key = Join-Path $root 'local\android-signing\wiley-debug.keystore'
if (-not (Test-Path -LiteralPath $key)) {
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $key) | Out-Null
    & $keytool -genkeypair -keystore $key -storepass android -keypass android -alias androiddebugkey -keyalg RSA -keysize 2048 -validity 10000 -dname 'CN=Android Debug,O=Android,C=US'
    if ($LASTEXITCODE -ne 0) { throw 'Failed to create the debug signing key.' }
}
$gradle = Get-Command gradle -ErrorAction SilentlyContinue
if ($gradle) { $gradlePath = $gradle.Source }
else {
    $cached = Join-Path $env:USERPROFILE '.gradle\wrapper\dists\gradle-8.9-bin'
    $gradlePath = Get-ChildItem -LiteralPath $cached -Filter gradle.bat -Recurse -File -ErrorAction SilentlyContinue | Select-Object -First 1 -ExpandProperty FullName
    if (-not $gradlePath) { throw 'Gradle 8.9 was not found. Install it or add it to PATH.' }
}
$arguments = @('-p', (Join-Path $root 'android'), '--no-daemon')
if ($Offline) { $arguments += '--offline' }
$arguments += 'assembleDebug'
& $gradlePath @arguments
if ($LASTEXITCODE -ne 0) { throw 'Failed to build the APK.' }
