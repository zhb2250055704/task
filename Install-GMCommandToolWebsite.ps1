$ErrorActionPreference = 'Stop'

$ToolDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$StartScript = Join-Path $ToolDir 'Start-GMCommandTool.ps1'
$TaskName = 'GMCommandToolAutoStart'
$Port = 9092
$LocalUrl = "http://localhost:$Port/"

if (-not (Test-Path -LiteralPath $StartScript)) {
    throw "Start script not found: $StartScript"
}

$PowerShell = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
$Action = New-ScheduledTaskAction -Execute $PowerShell -Argument "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$StartScript`""
$Trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$Settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit (New-TimeSpan -Hours 0) `
    -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 1)

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $Action `
    -Trigger $Trigger `
    -Settings $Settings `
    -Description 'Start GM Command Tool website after Windows logon.' `
    -Force | Out-Null

& $StartScript

$desktop = [Environment]::GetFolderPath('Desktop')
$shortcutPath = Join-Path $desktop 'GM Command Tool.url'
$shortcut = @"
[InternetShortcut]
URL=$LocalUrl
IconFile=%SystemRoot%\System32\SHELL32.dll
IconIndex=220
"@
Set-Content -LiteralPath $shortcutPath -Value $shortcut -Encoding ASCII

$lanIp = Get-NetIPAddress -AddressFamily IPv4 |
    Where-Object {
        $_.IPAddress -ne '127.0.0.1' -and
        $_.IPAddress -notlike '169.254*' -and
        $_.PrefixOrigin -ne 'WellKnown'
    } |
    Select-Object -ExpandProperty IPAddress -First 1

$isAdmin = ([Security.Principal.WindowsPrincipal] [Security.Principal.WindowsIdentity]::GetCurrent()).
    IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)

if ($isAdmin) {
    $ruleName = 'GM Command Tool Website 9092'
    $existingRule = Get-NetFirewallRule -DisplayName $ruleName -ErrorAction SilentlyContinue
    if (-not $existingRule) {
        New-NetFirewallRule `
            -DisplayName $ruleName `
            -Direction Inbound `
            -Action Allow `
            -Protocol TCP `
            -LocalPort $Port `
            -Profile Private `
            -ErrorAction SilentlyContinue | Out-Null
    }
}

Write-Host 'GM Command Tool website access has been installed.'
Write-Host "Local URL: $LocalUrl"
if ($lanIp) {
    Write-Host "LAN URL: http://$lanIp`:$Port/"
}
Write-Host "Desktop shortcut: $shortcutPath"
if (-not $isAdmin) {
    Write-Host 'Firewall rule was not changed because this script is not running as administrator.'
}
