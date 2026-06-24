param()

$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$repoDir = "D:\voice_clone_models\GPT-SoVITS"
$condaBat = if (Test-Path "D:\anaconda\condabin\conda.bat") { "D:\anaconda\condabin\conda.bat" } else { "conda.bat" }
$venvPython = Join-Path $root ".venv\Scripts\python.exe"
$installScript = Join-Path $repoDir "install.ps1"
$apiScript = Join-Path $repoDir "api_v2.py"
$preferredDevice = if ($env:GPT_SOVITS_DEVICE) { $env:GPT_SOVITS_DEVICE } else { "CPU" }
$sources = @("HF", "HF-Mirror", "ModelScope")

function Assert-Command {
    param([string]$Command, [string]$Message)
    if (-not (Get-Command $Command -ErrorAction SilentlyContinue)) {
        throw $Message
    }
}

function Invoke-CmdChecked {
    param([string]$CommandLine, [string]$FailureMessage)
    & cmd.exe /c $CommandLine
    if ($LASTEXITCODE -ne 0) {
        throw $FailureMessage
    }
}

function Test-CondaEnv {
    $envList = & cmd.exe /c "call `"$condaBat`" env list"
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to query conda environments."
    }
    return $envList -match "(?m)^GPTSoVits\s"
}

function Get-RecommendedDevice {
    if ($preferredDevice -in @("CU126", "CU128", "CPU")) {
        return $preferredDevice
    }
    try {
        $driverLine = (& nvidia-smi | Select-String "CUDA Version").ToString()
        if ($driverLine -match "CUDA Version:\s+12\.[6-9]") {
            return "CU126"
        }
    } catch {
    }
    Write-Host "GPU driver is below CUDA 12.6 or not detectable. Installing GPT-SoVITS in CPU mode for now."
    return "CPU"
}

function Invoke-OfficialInstall {
    param([string]$Device, [string]$Source)
    $command = "call `"$condaBat`" activate GPTSoVits && cd /d `"$repoDir`" && powershell -NoProfile -ExecutionPolicy Bypass -File `"$installScript`" -Device $Device -Source $Source"
    & cmd.exe /c $command
    return $LASTEXITCODE -eq 0
}

function Test-GptDependenciesReady {
    if (-not (Test-Path $repoDir)) { return $false }
    if (-not (Test-Path $apiScript)) { return $false }
    if (-not (Test-Path (Join-Path $repoDir 'GPT_SoVITS\pretrained_models\sv'))) { return $false }
    if (-not (Test-Path (Join-Path $repoDir 'GPT_SoVITS\text\G2PWModel'))) { return $false }
    if (-not (Test-CondaEnv)) { return $false }

    $checkCmd = @(
        "call `"$condaBat`" activate GPTSoVits",
        'python -c "import numpy, pyopenjtalk, opencc, jieba_fast, fastapi, librosa"'
    ) -join ' && '
    & cmd.exe /c $checkCmd | Out-Null
    return $LASTEXITCODE -eq 0
}

Assert-Command git "git is required for voice stack installation."
Assert-Command powershell "powershell is required for voice stack installation."

if (-not (Test-Path "D:\voice_clone_models")) {
    New-Item -ItemType Directory -Path "D:\voice_clone_models" | Out-Null
}

if (-not (Test-Path $repoDir)) {
    Write-Host "Cloning GPT-SoVITS repository..."
    Invoke-CmdChecked "git clone https://github.com/RVC-Boss/GPT-SoVITS.git `"$repoDir`"" "Failed to clone GPT-SoVITS."
}

if (-not (Test-CondaEnv)) {
    Write-Host "Creating conda environment GPTSoVits..."
    Invoke-CmdChecked "call `"$condaBat`" create -n GPTSoVits python=3.10 -y" "Failed to create GPTSoVits conda environment."
}

if (-not (Test-Path $apiScript)) {
    throw "api_v2.py is missing under $repoDir"
}

if (-not (Test-GptDependenciesReady)) {
    if (-not (Test-Path $installScript)) {
        throw "install.ps1 is missing under $repoDir"
    }
    $device = Get-RecommendedDevice
    $installed = $false
    foreach ($source in $sources) {
        Write-Host "Running GPT-SoVITS install.ps1 with device=$device source=$source ..."
        if (Invoke-OfficialInstall -Device $device -Source $source) {
            $installed = $true
            break
        }
        Write-Host "Install source failed: $source"
    }
    if (-not $installed) {
        throw "GPT-SoVITS install.ps1 failed for all configured sources."
    }
} else {
    Write-Host "GPT-SoVITS dependencies already ready. Skipping reinstall."
}

if (-not (Test-Path $venvPython)) {
    throw "Missing local virtualenv Python: $venvPython"
}

Write-Host "Installing faster-whisper into local app venv if needed..."
& $venvPython -m pip install --disable-pip-version-check faster-whisper
if ($LASTEXITCODE -ne 0) {
    throw "Failed to install faster-whisper into the app virtualenv."
}

Write-Host "Voice stack check complete."
