$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot

# Edge TTS provider: natural Japanese voice, cool/calm/researcher style
$env:ASSISTANT_TTS_PROVIDER = "edge-tts"
$env:ASSISTANT_TTS_VOICE = "ja-JP-NanamiNeural"

$ElectronExe = Join-Path $Root "node_modules\electron\dist\electron.exe"
$ElectronCmd = Join-Path $Root "node_modules\.bin\electron.cmd"

if (Test-Path $ElectronExe) {
  Push-Location $Root
  try {
    & $ElectronExe "desktop/main.js"
  } finally {
    Pop-Location
  }
  exit
}

if (Test-Path $ElectronCmd) {
  Push-Location $Root
  try {
    & $ElectronCmd "desktop/main.js"
  } finally {
    Pop-Location
  }
  exit
}

Write-Host "Electron is not installed yet. Run: npm install"
Write-Host "Falling back to the browser workbench."

$env:PYTHONPATH = Join-Path $Root "src"
$Python = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $Python)) {
  $Python = "python"
}
Start-Process -FilePath $Python -ArgumentList "-m assistant_app" -WorkingDirectory $Root -WindowStyle Hidden
Start-Sleep -Seconds 2
Start-Process "http://127.0.0.1:8765"
