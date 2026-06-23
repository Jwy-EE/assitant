@echo off
setlocal
cd /d %~dp0

:: ── Python 路径 ──
set "PYTHONPATH=src"

:: ── TTS ──
set "ASSISTANT_TTS_PROVIDER=edge-tts"
set "ASSISTANT_TTS_VOICE=ja-JP-NanamiNeural"

:: ── ASR（注释掉 = 用 Google fallback；取消注释 = 用本地 faster-whisper）──
:: set "ASSISTANT_ASR_PROVIDER=faster_whisper"
:: set "ASSISTANT_ASR_MODEL=medium"
:: set "ASSISTANT_ASR_DEVICE=cuda"
:: set "ASSISTANT_ASR_COMPUTE=float16"

if exist node_modules\electron\dist\electron.exe (
  start "DeepSeek Companion" cmd /c "set PYTHONPATH=src && set ASSISTANT_TTS_PROVIDER=edge-tts && set ASSISTANT_TTS_VOICE=ja-JP-NanamiNeural && start /b node_modules\electron\dist\electron.exe desktop\main.js"
  exit /b 0
)
if exist node_modules\.bin\electron.cmd (
  start "DeepSeek Companion" cmd /c "set PYTHONPATH=src && set ASSISTANT_TTS_PROVIDER=edge-tts && set ASSISTANT_TTS_VOICE=ja-JP-NanamiNeural && start /b node_modules\.bin\electron.cmd desktop\main.js"
  exit /b 0
)

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\run_desktop.ps1"
