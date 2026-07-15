$ErrorActionPreference = 'Stop'

$ToolDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Port = 9092

$existing = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
if ($existing) {
    exit 0
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
