$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$env:PYTHONPATH = Join-Path $Root "src"

# Edge TTS provider: natural Japanese voice, cool/calm/researcher style
$env:ASSISTANT_TTS_PROVIDER = "edge-tts"
$env:ASSISTANT_TTS_VOICE = "ja-JP-NanamiNeural"

$Python = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $Python)) {
  $Python = "python"
}
& $Python -m assistant_app
