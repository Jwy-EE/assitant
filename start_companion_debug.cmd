@echo off
setlocal
cd /d %~dp0
if exist node_modules\electron\dist\electron.exe (
  node_modules\electron\dist\electron.exe desktop\main.js
  pause
  exit /b %errorlevel%
)
if exist node_modules\.bin\electron.cmd (
  call node_modules\.bin\electron.cmd desktop\main.js
  pause
  exit /b %errorlevel%
)

echo Electron is not installed. Running fallback script.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\run_desktop.ps1"
pause