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

$ToolsDest = Join-Path $Claude "uefn-tools"
$AgentsDest = Join-Path $Claude "agents"
New-Item -ItemType Directory -Force -Path $ToolsDest, $AgentsDest | Out-Null

foreach ($Skill in @("uefn-mcp-automation", "uefn-gauntlet", "uefn-blender-assets")) {
    $Dest = Join-Path $Claude "skills\$Skill"
    New-Item -ItemType Directory -Force -Path $Dest | Out-Null
    Copy-Item -Force (Join-Path $Repo "skills\$Skill\SKILL.md") $Dest
    Write-Host "Installed skill  -> $Dest"
}
Copy-Item -Force (Join-Path $Repo "tools\*") $ToolsDest
Copy-Item -Force (Join-Path $Repo "agents\*.md") $AgentsDest
Write-Host "Installed tools  -> $ToolsDest"
Write-Host "Installed agents -> $AgentsDest (uefn-*.md)"

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
Write-Host "Optional: add the gauntlet TaskCompleted hook to your project's .claude\settings.json (see README)."
