param(
    [ValidateSet("scan", "watch", "weekly", "backup", "retry-ai", "doctor")][string]$Job = "scan",
    [string]$Config = ""
)
$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
if (-not $Config) { $Config = Join-Path $ProjectRoot "config.json" }
$PythonExe = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $PythonExe)) { throw "Run Setup.cmd first." }
# Scheduled Task processes may not inherit keys set in a terminal.
if (-not $env:OPENAI_API_KEY) {
    $env:OPENAI_API_KEY = [Environment]::GetEnvironmentVariable("OPENAI_API_KEY", "User")
}
Set-Location -LiteralPath $ProjectRoot
$LogRoot = Join-Path $ProjectRoot "logs"
New-Item -ItemType Directory -Path $LogRoot -Force | Out-Null
if ($Job -eq "watch") {
    & $PythonExe -m research_automation --config $Config watch
    exit $LASTEXITCODE
}
$JobLog = Join-Path $LogRoot ("scheduler-" + $Job + ".log")
& $PythonExe -m research_automation --config $Config $Job 2>&1 | Out-File -LiteralPath $JobLog -Append -Encoding utf8
exit $LASTEXITCODE
