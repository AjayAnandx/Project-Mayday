# Mayday desktop sensor (Brain V3 P8): run at logon in YOUR session (not as a service).
# The backend service runs in session 0 and cannot see your desktop; this agent sends only
# app categories, switch counts and idle/lock time (never window titles) to the backend.
#
#   powershell -ExecutionPolicy Bypass -File scripts\install_brain_sensor.ps1            # install + start
#   powershell -ExecutionPolicy Bypass -File scripts\install_brain_sensor.ps1 -Uninstall # remove
param([switch]$Uninstall)

$TaskName = "MaydayBrainSensor"
$Repo = Split-Path -Parent $PSScriptRoot

if ($Uninstall) {
    Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
    Write-Host "Removed $TaskName."
    exit 0
}

$python = (Get-Command python -ErrorAction Stop).Source
$pythonw = Join-Path (Split-Path -Parent $python) "pythonw.exe"
if (-not (Test-Path $pythonw)) { $pythonw = $python }

$action = New-ScheduledTaskAction -Execute $pythonw -Argument "-m backend.brain.sensor_agent" -WorkingDirectory $Repo
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1)
$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings `
    -Principal $principal -Description "Mayday Brain desktop sensor (app categories + idle; no titles)" -Force | Out-Null
Start-ScheduledTask -TaskName $TaskName
Write-Host "Installed and started $TaskName ($pythonw -m backend.brain.sensor_agent in $Repo)."
Write-Host "Check: http://127.0.0.1:8771/api/brain/sensors  (desktop.online should become true within ~30 s)"
