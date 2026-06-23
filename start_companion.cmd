@echo off
setlocal
cd /d %~dp0

:: Set Edge TTS as the voice provider - use cmd /c to pass env vars
set "ASSISTANT_TTS_PROVIDER=edge-tts"
set "ASSISTANT_TTS_VOICE=ja-JP-NanamiNeural"

if exist node_modules\electron\dist\electron.exe (
  start "DeepSeek Companion" cmd /c "set ASSISTANT_TTS_PROVIDER=edge-tts && set ASSISTANT_TTS_VOICE=ja-JP-NanamiNeural && start /b node_modules\electron\dist\electron.exe desktop\main.js"
  exit /b 0
)
if exist node_modules\.bin\electron.cmd (
  start "DeepSeek Companion" cmd /c "set ASSISTANT_TTS_PROVIDER=edge-tts && set ASSISTANT_TTS_VOICE=ja-JP-NanamiNeural && start /b node_modules\.bin\electron.cmd desktop\main.js"
  exit /b 0
)

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\run_desktop.ps1"