@echo off
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\register-tasks.ps1" %*
pause
