@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Run setup.cmd first to install Wencheng's Python dependencies.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" -X utf8 scripts\wencheng.py start --open %*
if errorlevel 1 (
  pause
  exit /b 1
)
