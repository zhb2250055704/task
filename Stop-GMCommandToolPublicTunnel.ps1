$ErrorActionPreference = 'Stop'

$ToolDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Cloudflared = Join-Path $ToolDir 'runtime\cloudflared.exe'
$PublicUrlFile = Join-Path $ToolDir 'public-url.txt'
$DesktopShortcut = Join-Path ([Environment]::GetFolderPath('Desktop')) 'GM Command Tool Public.url'
$Port = 9092

Get-CimInstance Win32_Process -Filter "Name='cloudflared.exe'" -ErrorAction SilentlyContinue |
    Where-Object { $_.ExecutablePath -eq $Cloudflared } |
    ForEach-Object {
        Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
    }

Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
    Where-Object {
        $_.CommandLine -and
        $_.CommandLine -like '*localtunnel*' -and
        $_.CommandLine -like "*$Port*"
    } |
    ForEach-Object {
        Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
    }

Remove-Item -LiteralPath $PublicUrlFile, $DesktopShortcut -Force -ErrorAction SilentlyContinue

Write-Host 'GM Command Tool public website has been stopped.'
