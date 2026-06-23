$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot

# ── Python 路径（由 app.py main 内部设 PYTHONUTF8）──
$env:PYTHONPATH = Join-Path $Root "src"

# ── TTS ──
$env:ASSISTANT_TTS_PROVIDER = "edge-tts"
$env:ASSISTANT_TTS_VOICE = "ja-JP-NanamiNeural"

# ── ASR（取消注释以启用本地 faster-whisper）──
# $env:ASSISTANT_ASR_PROVIDER = "faster_whisper"
# $env:ASSISTANT_ASR_MODEL = "medium"
# $env:ASSISTANT_ASR_DEVICE = "cuda"
# $env:ASSISTANT_ASR_COMPUTE = "float16"

$Python = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $Python)) {
  $Python = "python"
}
& $Python -m assistant_app
