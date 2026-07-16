$ErrorActionPreference = 'Stop'

$ToolDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$StartScript = Join-Path $ToolDir 'Start-GMCommandTool.ps1'
$PublicUrlFile = Join-Path $ToolDir 'public-url.txt'
$TunnelOutLog = Join-Path $ToolDir 'public-website.out.log'
$TunnelErrLog = Join-Path $ToolDir 'public-website.err.log'
$DesktopShortcut = Join-Path ([Environment]::GetFolderPath('Desktop')) 'GM Command Tool Public.url'
$Port = 9092
$PreferredSubdomain = 'tu-gm-command-tool-20260716'

function Stop-ExistingLocalTunnel {
    Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
        Where-Object {
            $_.CommandLine -and
            $_.CommandLine -like '*localtunnel*' -and
            $_.CommandLine -like "*$Port*"
        } |
        ForEach-Object {
            Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
        }
}

function Start-LocalTunnel {
    param(
        [string[]] $Arguments
    )

    Remove-Item -LiteralPath $TunnelOutLog, $TunnelErrLog -Force -ErrorAction SilentlyContinue
    $npx = (Get-Command npx.cmd -ErrorAction SilentlyContinue).Source
    if (-not $npx) {
        throw 'npx.cmd was not found. Please install Node.js first.'
    }

    $process = Start-Process `
        -FilePath $npx `
        -ArgumentList $Arguments `
        -WorkingDirectory $ToolDir `
        -WindowStyle Hidden `
        -RedirectStandardOutput $TunnelOutLog `
        -RedirectStandardError $TunnelErrLog `
        -PassThru

    $deadline = (Get-Date).AddSeconds(60)
    while ((Get-Date) -lt $deadline) {
        Start-Sleep -Milliseconds 500

        $logText = ''
        foreach ($log in @($TunnelOutLog, $TunnelErrLog)) {
            if (Test-Path -LiteralPath $log) {
                $logText += "`n" + (Get-Content -LiteralPath $log -Raw -ErrorAction SilentlyContinue)
            }
        }

        $match = [regex]::Match($logText, 'https://[a-zA-Z0-9-]+\.loca\.lt')
        if ($match.Success) {
            return @{
                Url = $match.Value.TrimEnd('/')
                Process = $process
            }
        }

        if ($process.HasExited) {
            break
        }
    }

    if (-not $process.HasExited) {
        Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue
    }
    return $null
}

& $StartScript
Stop-ExistingLocalTunnel
Remove-Item -LiteralPath $PublicUrlFile -Force -ErrorAction SilentlyContinue

$baseArgs = @('--yes', 'localtunnel', '--port', "$Port", '--local-host', '127.0.0.1')
$result = $null
$preferredUrl = "https://$PreferredSubdomain.loca.lt"
for ($attempt = 1; $attempt -le 3; $attempt++) {
    $attemptResult = Start-LocalTunnel -Arguments ($baseArgs + @('--subdomain', $PreferredSubdomain))
    if ($attemptResult -and $attemptResult.Url -eq $preferredUrl) {
        $result = $attemptResult
        break
    }

    Stop-ExistingLocalTunnel
    if ($attempt -lt 3) {
        Start-Sleep -Seconds 5
    }
}

if (-not $result) {
    $result = Start-LocalTunnel -Arguments $baseArgs
}

if (-not $result) {
    $lastLog = ''
    foreach ($log in @($TunnelOutLog, $TunnelErrLog)) {
        if (Test-Path -LiteralPath $log) {
            $lastLog += "`n" + (Get-Content -LiteralPath $log -Raw -ErrorAction SilentlyContinue)
        }
    }
    throw "Public website was not generated. $lastLog"
}

$publicUrl = $result.Url
Set-Content -LiteralPath $PublicUrlFile -Value $publicUrl -Encoding ASCII

$shortcut = @"
[InternetShortcut]
URL=$publicUrl/
IconFile=%SystemRoot%\System32\SHELL32.dll
IconIndex=220
"@
Set-Content -LiteralPath $DesktopShortcut -Value $shortcut -Encoding ASCII

Write-Host 'GM Command Tool free public website is ready.'
Write-Host "Public URL: $publicUrl/"
Write-Host "Desktop shortcut: $DesktopShortcut"
