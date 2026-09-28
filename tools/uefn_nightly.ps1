<#
    Nightly unattended playtest for a UEFN project (meant for Windows Task Scheduler).

    Skips quietly when UEFN is not running or a dialog is blocking it - it never starts UEFN itself.
    Results land in <tools>\playtest-history\<yyyy-MM-dd_HHmm>\ (report.json, client_end.png,
    run.log) plus one summary line per run in playtest-history\history.log.

    Example:
        powershell -File uefn_nightly.ps1 -Project "C:\Users\me\Documents\uefnProjects\MyIsland\Content"

    Register (runs only while you are logged in - it needs the Fortnite client window):
        schtasks /Create /TN "UEFN Nightly Playtest" /SC DAILY /ST 03:00 /IT /F /TR 'powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "<path>\uefn_nightly.ps1" -Project "<path>\Content"'
    Remove:
        schtasks /Delete /TN "UEFN Nightly Playtest" /F
#>
param(
    [Parameter(Mandatory = $true)][string]$Project,
    [string]$Python = "",
    [int]$TimeoutSeconds = 900
)

if (-not $Python) {
    $Found = Get-Command python -ErrorAction SilentlyContinue
    if (-not $Found) { $Found = Get-Command py -ErrorAction SilentlyContinue }
    if (-not $Found) { throw "No Python found on PATH - pass -Python <path to python.exe>." }
    $Python = $Found.Source
}

$Tools = Split-Path -Parent $MyInvocation.MyCommand.Path
$HistoryRoot = Join-Path $Tools "playtest-history"
$Stamp = Get-Date -Format "yyyy-MM-dd_HHmm"
$OutDir = Join-Path $HistoryRoot $Stamp
New-Item -ItemType Directory -Force -Path $OutDir | Out-Null
$HistoryLog = Join-Path $HistoryRoot "history.log"

& $Python (Join-Path $Tools "uefn_watch.py") *> (Join-Path $OutDir "health.log")
$Health = $LASTEXITCODE
if ($Health -eq 2 -or $Health -eq 3) {
    $Why = if ($Health -eq 3) { "UEFN not running" } else { "modal dialog open" }
    Add-Content -Path $HistoryLog -Value "$Stamp  SKIPPED  ($Why)" -Encoding utf8
    exit 0
}

& $Python -u (Join-Path $Tools "uefn_playtest.py") --project $Project --timeout $TimeoutSeconds --out $OutDir *> (Join-Path $OutDir "run.log")
$Code = $LASTEXITCODE

$Summary = "no report"
$ReportPath = Join-Path $OutDir "report.json"
if (Test-Path $ReportPath) {
    $Report = Get-Content $ReportPath -Raw -Encoding utf8 | ConvertFrom-Json
    $Failed = @($Report.results | Where-Object { $_.status -eq "FAIL" } | ForEach-Object { $_.id })
    $Summary = if ($Report.summary) { $Report.summary } else { "no END seen" }
    if ($Failed.Count -gt 0) { $Summary += "  FAILED: " + ($Failed -join ", ") }
    if ($Report.runtime_errors.Count -gt 0) { $Summary += "  runtime errors: $($Report.runtime_errors.Count)" }
}
$Status = switch ($Code) { 0 { "PASS" } 1 { "FAIL" } default { "ERROR" } }
Add-Content -Path $HistoryLog -Value "$Stamp  $Status  $Summary  -> $OutDir" -Encoding utf8
exit $Code
