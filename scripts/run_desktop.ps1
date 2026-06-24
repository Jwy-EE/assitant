$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
& powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $Root "scripts\start_all_in_one.ps1")
