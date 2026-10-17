param([switch]$Clean)
$ErrorActionPreference = 'Stop'

# Legacy Electron test profiles only. No wildcard deletion of the TEMP tree.
$testTempRoot = [IO.Path]::GetFullPath((Join-Path $env:LOCALAPPDATA 'Temp')).TrimEnd('\')
$resolvedTestTemp = (Resolve-Path -LiteralPath $testTempRoot).Path.TrimEnd('\')
if ($resolvedTestTemp -ne $testTempRoot -or (Split-Path $resolvedTestTemp -Leaf) -ne 'Temp') { throw 'Unexpected TEMP location' }
$testPrefixes = @('wiley-cloud','wiley-completion','wiley-device-audio','wiley-distribution','wiley-document-summary','wiley-docx','wiley-history','wiley-monitor','wiley-openvoice-ui','wiley-qwen-live','wiley-scroll','wiley-settings-layout','wiley-setup-cloud','wiley-setup-first','wiley-startup','wiley-startup-retry','wiley-streaming','wileyai-backups','wileyai-calendar','wileyai-calendar-alerts','wileyai-conversation','wileyai-documents','wileyai-e2e','wileyai-intents','wileyai-live','wileyai-memory','wileyai-routines','wileyai-spaces','wileyai-websearch','wileyai-workflows')
$testPattern = '^(?:' + (($testPrefixes | ForEach-Object { [regex]::Escape($_) }) -join '|') + ')-[A-Za-z0-9]{6}$'
$testProfiles = @()
$testSkipped = @()
foreach ($candidate in (Get-ChildItem -LiteralPath $resolvedTestTemp -Directory -Force)) {
  if ($candidate.Name -cnotmatch $testPattern) { continue }
  $target = [IO.Path]::GetFullPath($candidate.FullName)
  if ([IO.Path]::GetDirectoryName($target) -ne $resolvedTestTemp -or -not $target.StartsWith($resolvedTestTemp + '\', [StringComparison]::OrdinalIgnoreCase)) { throw 'Cleanup path escaped TEMP' }
  if (($candidate.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0 -or -not (Test-Path -LiteralPath (Join-Path $target 'electron') -PathType Container) -or -not (Test-Path -LiteralPath (Join-Path $target 'wileyai.db') -PathType Leaf)) { $testSkipped += $candidate.Name; continue }
  # A recently created test may still be running. New tests no longer use TEMP.
  if ($candidate.CreationTimeUtc -gt [DateTime]::UtcNow.AddMinutes(-10)) { $testSkipped += $candidate.Name; continue }
  $stack = New-Object 'System.Collections.Generic.Stack[string]'
  $stack.Push($target)
  [long]$bytes = 0
  $safe = $true
  while ($stack.Count -gt 0 -and $safe) {
    foreach ($entry in (Get-ChildItem -LiteralPath $stack.Pop() -Force)) {
      if (($entry.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) { $safe = $false; break }
      if ($entry.PSIsContainer) { $stack.Push($entry.FullName) } else { $bytes += $entry.Length }
    }
  }
  if (-not $safe) { $testSkipped += $candidate.Name; continue }
  $testProfiles += [pscustomobject]@{ Path=$target; Bytes=$bytes }
}
[long]$totalBytes = ($testProfiles | Measure-Object -Property Bytes -Sum).Sum
if ($Clean) {
  foreach ($testProfile in $testProfiles) {
    # Recheck the final literal path directly before recursive deletion.
    $finalTarget = (Resolve-Path -LiteralPath $testProfile.Path).Path
    if ([IO.Path]::GetDirectoryName($finalTarget) -ne $resolvedTestTemp -or (Split-Path $finalTarget -Leaf) -cnotmatch $testPattern) { throw 'Cleanup path changed' }
    Remove-Item -LiteralPath $finalTarget -Recurse -Force
  }
}
[pscustomobject]@{ Mode=$(if ($Clean) {'Deleted'} else {'Preview only; run with -Clean to delete'}); Folders=$testProfiles.Count; GiB=[math]::Round($totalBytes/1GB,2); Skipped=$testSkipped.Count; Root=$resolvedTestTemp } | Format-List
if ($testSkipped.Count) { Write-Output ('Skipped links, recent or incomplete profiles: ' + ($testSkipped -join ', ')) }
