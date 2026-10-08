@echo off
setlocal
cd /d "%~dp0"
set "TCL_LIBRARY=%~dp0runtime/tcl/tcl8.6"
set "TK_LIBRARY=%~dp0runtime/tcl/tk8.6"
"%~dp0runtime\pythonw.exe" -m research_automation.gui --config "%~dp0..\..\private-qa\config.json" %*
exit /b %errorlevel%
