param([string]$Config = "")
$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
if (-not $Config) { $Config = Join-Path $ProjectRoot "config.json" }
$PythonExe = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$PythonWindowExe = Join-Path $ProjectRoot ".venv\Scripts\pythonw.exe"
if (-not (Test-Path -LiteralPath $PythonWindowExe)) { throw "Run Setup.cmd first (Python with Tcl/Tk is required)." }
& $PythonExe -c "import tkinter"
if ($LASTEXITCODE -ne 0) { throw "Tcl/Tk is missing. Install the Tcl/Tk option from the official Python installer, then rerun Setup.cmd." }
$Arguments = @("-m", "research_automation.gui", "--config", ('"' + $Config + '"'))
Start-Process -FilePath $PythonWindowExe -ArgumentList $Arguments -WorkingDirectory $ProjectRoot
