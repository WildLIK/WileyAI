param(
    [Parameter(Mandatory=$true)][string]$TestName,
    [switch]$Media,
    [string]$Adb = "$env:LOCALAPPDATA\Android\Sdk\platform-tools\adb.exe"
)
$ErrorActionPreference = 'Stop'
$package = 'ru.wildlik.wileyai.mobile'
$runner = "$package.test/$package.StageOneInstrumentation"
$service = "$package/.HandsFreeService"
$running = (& $Adb shell dumpsys activity services $service | Out-String) -match 'isForeground=true'
$prefs = (& $Adb shell run-as $package cat shared_prefs/wiley-mobile.xml | Out-String)
[xml]$xml = $prefs
$enabled = @($xml.map.boolean | Where-Object { $_.name -eq 'handsfree_enabled' -and $_.value -eq 'true' }).Count -gt 0
$result = 1
try {
    $arguments = @('shell','am','instrument','-w','-e','only',$TestName)
    if ($Media) { $arguments += @('-e','media','true') }
    $output = & $Adb @arguments $runner
    $result = $LASTEXITCODE
    $output | Write-Output
    $joined = $output | Out-String
    if ($joined -match 'INSTRUMENTATION_STATUS_CODE: -[0-9]|INSTRUMENTATION_FAILED|FAILURES!!!' -or $joined -notmatch 'WileyAI Android: 1 tests passed') { $result = 1 }
} finally {
    if ($running -and $enabled) {
        $window = & $Adb shell dumpsys window | Out-String
        if ($window -match 'mDreamingLockscreen=true') {
            Write-Warning 'Телефон заблокирован: откройте WileyAI и восстановите фоновую службу после разблокировки.'
            $result = 1
        } else {
            & $Adb shell monkey -p $package -c android.intent.category.LAUNCHER 1 | Out-Null
            & $Adb shell run-as $package am start-foreground-service --user 0 -n $service -a wiley.assistant.ENABLE
            $restored = $false
            for ($attempt = 0; $attempt -lt 20; $attempt++) {
                $after = & $Adb shell dumpsys activity services $service | Out-String
                if ($after -match 'isForeground=true') { $restored = $true; break }
                Start-Sleep -Milliseconds 250
            }
            if (-not $restored) { Write-Warning 'Фоновая служба WileyAI не подтвердила запуск.'; $result = 1 }
        }
    }
}
exit $result
