$ErrorActionPreference = 'Stop'

$ToolDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$StartScript = Join-Path $ToolDir 'Start-GMCommandTool.ps1'
$TaskName = 'GMCommandToolAutoStart'
$PowerShell = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
$Action = New-ScheduledTaskAction -Execute $PowerShell -Argument "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$StartScript`""
$Trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$Settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Hours 0)

Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Trigger -Settings $Settings -Description 'Start GM Command Tool local website after Windows logon.' -Force | Out-Null

& $StartScript

Write-Host "GM Command Tool auto-start has been installed."
Write-Host "URL: http://localhost:9092/"
