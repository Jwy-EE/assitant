@echo off
setlocal
cd /d %~dp0
start "" powershell -WindowStyle Hidden -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\start_all_in_one.ps1"
exit /b 0