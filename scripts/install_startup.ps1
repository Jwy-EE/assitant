$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$ScriptPath = Join-Path $Root "scripts\run_desktop.ps1"
$Action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$ScriptPath`""
$Trigger = New-ScheduledTaskTrigger -AtLogOn
$Settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
Register-ScheduledTask -TaskName "DeepSeekResearchCompanion" -Action $Action -Trigger $Trigger -Settings $Settings -Description "Start the DeepSeek desktop research companion after Windows logon." -Force | Out-Null
Write-Host "Installed startup task: DeepSeekResearchCompanion"

