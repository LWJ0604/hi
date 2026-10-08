@echo off
setlocal
cd /d "%~dp0"
set "TCL_LIBRARY=runtime/tcl/tcl8.6"
set "TK_LIBRARY=runtime/tcl/tk8.6"
"%~dp0runtime\python.exe" -c "from research_automation.config import Config; Config('qa-config.json').ensure_dirs()"
if errorlevel 1 exit /b 1
"%~dp0runtime\pythonw.exe" -m research_automation.gui --config "%~dp0qa-config.json" %*
exit /b %errorlevel%
