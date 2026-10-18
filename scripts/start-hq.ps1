param(
    [switch]$NoBrowser
)

$ErrorActionPreference = 'Stop'
$hqRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$runtime = Join-Path $hqRoot 'runtime'
$watchdog = Join-Path $hqRoot 'scripts\hq_watchdog.py'
$port = if ($env:DEV_HQ_WATCHDOG_PORT) { [int]$env:DEV_HQ_WATCHDOG_PORT } else { 32110 }

New-Item -ItemType Directory -Path $runtime -Force | Out-Null

$existing = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
if (-not $existing) {
    $python = (Get-Command python.exe -ErrorAction Stop).Source
    Start-Process -FilePath $python -ArgumentList @($watchdog, 'run', '--port', [string]$port) -WindowStyle Hidden | Out-Null

    $deadline = (Get-Date).AddSeconds(8)
    do {
        Start-Sleep -Milliseconds 250
        $existing = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
    } while (-not $existing -and (Get-Date) -lt $deadline)
}

if (-not $existing) {
    throw "Dev HQ Watchdog did not start on port $port"
}

$url = "http://127.0.0.1:$port/hq-status"
Write-Host "Dev HQ Watchdog: $url"
if (-not $NoBrowser) {
    Start-Process $url
}
