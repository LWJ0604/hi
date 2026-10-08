@echo off
cd /d "%~dp0"
".venv\Scripts\python.exe" -m research_automation --config config.json audit-results
pause
