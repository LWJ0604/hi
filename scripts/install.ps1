param([string]$Python = "", [switch]$RunDemo)
$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $ProjectRoot
if (-not (Test-Path -LiteralPath ".venv\Scripts\python.exe")) {
    if ($Python) {
        & $Python -m venv .venv
    } elseif (Get-Command py -ErrorAction SilentlyContinue) {
        & py -3.12 -m venv .venv
    } else {
        & python -m venv .venv
    }
    if ($LASTEXITCODE -ne 0) { throw "Install Python 3.12 first, or use -Python with its full executable path." }
}
$PythonExe = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
& $PythonExe -m pip install -r requirements.txt
if ($LASTEXITCODE -ne 0) { throw "Dependency installation failed." }
& $PythonExe -m pip install --no-deps -e .
if ($LASTEXITCODE -ne 0) { throw "Project installation failed." }
if (-not (Test-Path -LiteralPath "config.json")) {
    Copy-Item -LiteralPath "config.windows.json" -Destination "config.json"
}
& $PythonExe -c "from research_automation.config import Config; Config('config.json'); print('Configuration syntax OK. Select this PC inbox and vault in Start-GUI.cmd before analysis.')"
if ($LASTEXITCODE -ne 0) { throw "Configuration check failed; inspect config.json." }
if ($RunDemo) {
    $DemoConfig = Join-Path $ProjectRoot "demo-runtime\config.json"
    if (-not (Test-Path -LiteralPath $DemoConfig)) {
        & $PythonExe -m research_automation --config $DemoConfig init
        if ($LASTEXITCODE -ne 0) { throw "Demo initialization failed." }
        & $PythonExe -m research_automation --config $DemoConfig demo
        if ($LASTEXITCODE -ne 0) { throw "Demo data creation failed." }
    }
    & $PythonExe -m research_automation --config $DemoConfig scan
    if ($LASTEXITCODE -ne 0) { throw "Demo analysis failed." }
    & $PythonExe -m research_automation --config $DemoConfig weekly
    if ($LASTEXITCODE -ne 0) { throw "Demo weekly report failed." }
}
Write-Host "Ready. Run Start-Watch.cmd or install scheduled tasks with scripts\register-tasks.ps1."
