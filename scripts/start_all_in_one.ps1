param()

$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$pythonExe = Join-Path $root ".venv\Scripts\python.exe"
$voiceApiScript = Join-Path $root "voice_api_server_v2.py"
$backendPort = "8765"
$backendHealthUrl = "http://127.0.0.1:$backendPort/api/health"
$desktopEntry = Join-Path $root "desktop\main.js"
$electronExe = Join-Path $root "node_modules\electron\dist\electron.exe"
$electronCmd = Join-Path $root "node_modules\.bin\electron.cmd"
$installerScript = Join-Path $root "scripts\install_voice_stack.ps1"
$voiceApiPort = if ($env:VOICE_API_PORT) { $env:VOICE_API_PORT } else { "8767" }
$gptApiBase = if ($env:GPT_SOVITS_API_BASE) { $env:GPT_SOVITS_API_BASE } else { "http://127.0.0.1:9880" }
$voiceHealthUrl = "http://127.0.0.1:$voiceApiPort/api/health"
$voiceTtsUrl = "http://127.0.0.1:$voiceApiPort/tts"
$gptTtsUrl = "$($gptApiBase.TrimEnd('/'))/tts"
$gptRepo = if ($env:GPT_SOVITS_REPO) { $env:GPT_SOVITS_REPO } else { 'D:\voice_clone_models\GPT-SoVITS' }
$condaBat = if (Test-Path 'D:\anaconda\condabin\conda.bat') { 'D:\anaconda\condabin\conda.bat' } else { 'conda.bat' }
$gptStartCommand = if ($env:GPT_SOVITS_START_CMD) {
    $env:GPT_SOVITS_START_CMD
} else {
    "call `"$condaBat`" activate GPTSoVits && cd /d `"$gptRepo`" && python api_v2.py -a 127.0.0.1 -p 9880 -c GPT_SoVITS/configs/tts_infer.yaml"
}

function Test-HttpGet {
    param([string]$Url, [int]$TimeoutSec = 3)
    try {
        Invoke-RestMethod -Uri $Url -Method Get -TimeoutSec $TimeoutSec | Out-Null
        return $true
    } catch {
        return $false
    }
}

function Test-GptReady {
    try {
        $response = Invoke-WebRequest -UseBasicParsing -Uri $gptTtsUrl -Method Post -ContentType "application/json" -Body "{}" -TimeoutSec 5 -ErrorAction Stop
        return $response.StatusCode -in 200, 400, 422
    } catch {
        if ($_.Exception.Response -and $_.Exception.Response.StatusCode.value__ -in 400, 422) {
            return $true
        }
        return $false
    }
}

function Wait-Until {
    param([scriptblock]$Probe, [int]$RetryCount = 40, [int]$SleepMs = 1500)
    for ($i = 0; $i -lt $RetryCount; $i++) {
        if (& $Probe) {
            return $true
        }
        Start-Sleep -Milliseconds $SleepMs
    }
    return $false
}

function Assert-ReadyPath {
    param([string]$PathToCheck, [string]$FailureMessage)
    if (-not (Test-Path $PathToCheck)) {
        throw $FailureMessage
    }
}

function Ensure-VoiceStackReady {
    Assert-ReadyPath -PathToCheck $pythonExe -FailureMessage "Missing app Python: $pythonExe"
    Assert-ReadyPath -PathToCheck $voiceApiScript -FailureMessage "Missing voice bridge script: $voiceApiScript"
    Assert-ReadyPath -PathToCheck $gptRepo -FailureMessage "Missing GPT-SoVITS repo: $gptRepo . Run scripts\install_voice_stack.ps1 once."
    Assert-ReadyPath -PathToCheck (Join-Path $gptRepo 'api_v2.py') -FailureMessage "GPT-SoVITS api_v2.py is missing under $gptRepo"
    Assert-ReadyPath -PathToCheck $installerScript -FailureMessage "Missing installer helper: $installerScript"
}

function Start-GptSoVits {
    if (Test-GptReady) {
        Write-Host "GPT-SoVITS already running: $gptApiBase"
        return
    }

    Write-Host "Starting GPT-SoVITS..."
    Start-Process -FilePath 'cmd.exe' -ArgumentList @('/c', $gptStartCommand) -WorkingDirectory $root -WindowStyle Hidden | Out-Null
    if (-not (Wait-Until -Probe ${function:Test-GptReady} -RetryCount 80 -SleepMs 1500)) {
        throw "GPT-SoVITS did not become ready on $gptApiBase"
    }
}

function Start-VoiceApi {
    if (Test-HttpGet -Url $voiceHealthUrl) {
        Write-Host "Voice bridge already running: $voiceHealthUrl"
        return
    }
    Assert-ReadyPath -PathToCheck $pythonExe -FailureMessage "Missing Python: $pythonExe"
    Write-Host "Starting voice bridge API..."
    Start-Process -FilePath $pythonExe -ArgumentList @($voiceApiScript) -WorkingDirectory $root -WindowStyle Hidden | Out-Null
    if (-not (Wait-Until -Probe { Test-HttpGet -Url $voiceHealthUrl } -RetryCount 40 -SleepMs 1500)) {
        throw "Voice bridge failed to start on port $voiceApiPort"
    }
}

function Start-AppBackend {
    if (Test-HttpGet -Url $backendHealthUrl) {
        Write-Host "App backend already running: $backendHealthUrl"
        return
    }
    Assert-ReadyPath -PathToCheck $pythonExe -FailureMessage "Missing Python: $pythonExe"
    Write-Host "Starting app backend..."
    Start-Process -FilePath $pythonExe -ArgumentList @('-m', 'assistant_app') -WorkingDirectory $root -WindowStyle Hidden | Out-Null
    if (-not (Wait-Until -Probe { Test-HttpGet -Url $backendHealthUrl } -RetryCount 40 -SleepMs 750)) {
        throw "App backend failed to start on port $backendPort"
    }
}

function Warm-UpVoice {
    $warmupText = if ($env:GPT_SOVITS_WARMUP_TEXT) { $env:GPT_SOVITS_WARMUP_TEXT } else { 'konnichiwa' }
    $payload = @{ text = $warmupText; language = 'ja-JP'; voice = 'kurisu_ja'; style = 'serious' } | ConvertTo-Json
    Write-Host "Warming up GPT-SoVITS voice pipeline..."
    try {
        Invoke-WebRequest -UseBasicParsing -Uri $voiceTtsUrl -Method Post -ContentType 'application/json; charset=utf-8' -Body $payload -TimeoutSec 300 | Out-Null
        Write-Host "Voice warm-up complete."
    } catch {
        Write-Warning "Voice warm-up failed, continuing anyway: $($_.Exception.Message)"
    }
}

function Start-DesktopApp {
    if (Test-Path $electronExe) {
        Write-Host "Starting desktop app..."
        Start-Process -FilePath $electronExe -ArgumentList @($desktopEntry) -WorkingDirectory $root | Out-Null
        return
    }
    if (Test-Path $electronCmd) {
        Write-Host "Starting desktop app..."
        Start-Process -FilePath 'cmd.exe' -ArgumentList @('/c', "`"$electronCmd`" `"$desktopEntry`"") -WorkingDirectory $root | Out-Null
        return
    }
    throw 'Electron is not installed under node_modules.'
}

$env:PYTHONPATH = 'src'
$env:PYTHONUTF8 = '1'
$env:VOICE_API_PORT = $voiceApiPort
$env:GPT_SOVITS_API_BASE = $gptApiBase
$env:KURISU_VOICE_MODE = 'gpt-sovits'
$env:ASSISTANT_BACKEND_MANAGED = '1'
$env:ASSISTANT_TTS_PROVIDER = 'http'
$env:ASSISTANT_TTS_ENDPOINT = "http://127.0.0.1:$voiceApiPort/tts"
$env:ASSISTANT_TTS_VOICE = 'kurisu_ja'
$env:ASSISTANT_ASR_PROVIDER = 'faster_whisper'
$env:ASSISTANT_ASR_MODEL = if ($env:ASSISTANT_ASR_MODEL) { $env:ASSISTANT_ASR_MODEL } else { 'base' }
$env:ASSISTANT_ASR_DEVICE = if ($env:ASSISTANT_ASR_DEVICE) { $env:ASSISTANT_ASR_DEVICE } else { 'cuda' }
$env:ASSISTANT_ASR_COMPUTE = if ($env:ASSISTANT_ASR_COMPUTE) { $env:ASSISTANT_ASR_COMPUTE } else { 'float16' }
$env:GPT_SOVITS_WARMUP_TEXT = if ($env:GPT_SOVITS_WARMUP_TEXT) { $env:GPT_SOVITS_WARMUP_TEXT } else { 'konnichiwa' }

Write-Host 'One-click startup begins...'
Ensure-VoiceStackReady
Start-GptSoVits
Start-VoiceApi
Start-AppBackend
Warm-UpVoice
Start-DesktopApp
Write-Host 'All done.'