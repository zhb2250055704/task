$ErrorActionPreference = 'Stop'

$ToolDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Port = 9092
$ServerFile = Join-Path $ToolDir 'server.py'
$ExpectedBuild = (Get-FileHash -LiteralPath $ServerFile -Algorithm SHA256).Hash.Substring(0, 12).ToLowerInvariant()

$existing = @(Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue)
if ($existing) {
    try {
        $health = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/api/health" -TimeoutSec 3
        if ($health.ok -and $health.app -eq 'gm-command-tool' -and $health.build -eq $ExpectedBuild) {
            exit 0
        }
    } catch {}

    foreach ($conn in $existing) {
        $proc = Get-CimInstance Win32_Process -Filter "ProcessId=$($conn.OwningProcess)" -ErrorAction SilentlyContinue
        if ($proc -and $proc.CommandLine -like '*server.py*') {
            Stop-Process -Id $conn.OwningProcess -Force -ErrorAction SilentlyContinue
        }
    }
    Start-Sleep -Milliseconds 500

    if (Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue) {
        throw "Port $Port is occupied by another application."
    }
}

$pythonCandidates = @(
    'C:\Users\TU\AppData\Local\Programs\Python\Python310\pythonw.exe',
    'C:\Users\TU\AppData\Local\Programs\Python\Python310\python.exe'
)

$python = $pythonCandidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
if (-not $python) {
    $python = (Get-Command pythonw.exe -ErrorAction SilentlyContinue).Source
}
if (-not $python) {
    $python = (Get-Command python.exe -ErrorAction SilentlyContinue).Source
}
if (-not $python) {
    throw 'No usable Python interpreter found.'
}

$env:GM_OPEN_BROWSER = '0'
Start-Process -FilePath $python -ArgumentList @('server.py', $Port, '--no-browser') -WorkingDirectory $ToolDir -WindowStyle Hidden

for ($attempt = 0; $attempt -lt 20; $attempt++) {
    Start-Sleep -Milliseconds 250
    try {
        $health = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/api/health" -TimeoutSec 2
        if ($health.ok -and $health.build -eq $ExpectedBuild) {
            exit 0
        }
    } catch {}
}

throw 'GM Command Tool did not become ready in time.'
