@echo off
setlocal
cd /d "%~dp0"
set "TCL_LIBRARY=runtime/tcl/tcl8.6"
set "TK_LIBRARY=runtime/tcl/tk8.6"
"%~dp0runtime\python.exe" -m unittest discover -s tests -v
pause
