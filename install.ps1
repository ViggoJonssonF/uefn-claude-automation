<#
    Installs the uefn-mcp-automation skill and tools for Claude Code on this machine.

      skills\uefn-mcp-automation  ->  %USERPROFILE%\.claude\skills\uefn-mcp-automation
      tools\*                     ->  %USERPROFILE%\.claude\uefn-tools\

    Existing files with the same names are overwritten; nothing else is touched.
    Run from the repo root:  powershell -ExecutionPolicy Bypass -File install.ps1
#>
$ErrorActionPreference = "Stop"
$Repo = Split-Path -Parent $MyInvocation.MyCommand.Path
$Claude = Join-Path $env:USERPROFILE ".claude"

$SkillDest = Join-Path $Claude "skills\uefn-mcp-automation"
$ToolsDest = Join-Path $Claude "uefn-tools"
New-Item -ItemType Directory -Force -Path $SkillDest, $ToolsDest | Out-Null

Copy-Item -Force (Join-Path $Repo "skills\uefn-mcp-automation\SKILL.md") $SkillDest
Copy-Item -Force (Join-Path $Repo "tools\*") $ToolsDest

Write-Host "Installed skill -> $SkillDest"
Write-Host "Installed tools -> $ToolsDest"

$Python = Get-Command python -ErrorAction SilentlyContinue
if (-not $Python) {
    Write-Warning "Python 3.10+ not found on PATH - the tools need it."
} else {
    & $Python.Source -c "import PIL" 2>$null
    if ($LASTEXITCODE -ne 0) {
        Write-Warning "Pillow is missing (needed for screenshots): $($Python.Source) -m pip install pillow"
    }
}
Write-Host ""
Write-Host "Next: copy verse\AutoTest.verse into your project and start it from a device (see README)."
