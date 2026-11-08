@echo off
setlocal
cd /d "%~dp0"
where py >nul 2>nul
if errorlevel 1 (
  python -X utf8 scripts\setup.py
) else (
  py -3 -X utf8 scripts\setup.py
)
if errorlevel 1 (
  echo Install Python 3.11 or newer, then run setup.cmd again.
  pause
  exit /b 1
)
echo Run start.cmd to open Wencheng.
pause
