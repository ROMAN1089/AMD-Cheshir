@echo off
setlocal
cd /d "%~dp0"
title SnapSell
if not exist ".venv\Scripts\python.exe" (
  echo Python environment is missing. Follow the Local setup section in ReadMe.md.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" -X utf8 "scripts\launch.py" %*
if errorlevel 1 pause
