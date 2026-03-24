# Stop PolySuite dashboard/bot processes and free the dashboard port (stale instance fix).
# Usage: .\scripts\stop_polysuite.ps1

Get-Process python* -ErrorAction SilentlyContinue | ForEach-Object {
    try {
        $cmd = (Get-CimInstance Win32_Process -Filter "ProcessId=$($_.Id)" -ErrorAction SilentlyContinue).CommandLine
        if ($cmd -like "*main.py*" -or $cmd -like "*polysuite*" -or $cmd -like "*PolySuite*") {
            Stop-Process -Id $_.Id -Force
            Write-Host "Stopped PID $($_.Id)"
        }
    } catch {}
}

# Whatever still holds DASHBOARD_PORT (default 5000) — e.g. orphaned Waitress
$port = 5000
if ($env:DASHBOARD_PORT -match '^\d+$') { $port = [int]$env:DASHBOARD_PORT }
try {
    Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue | ForEach-Object {
        $owning = [int]$_.OwningProcess
        if ($owning -gt 0) {
            Stop-Process -Id $owning -Force -ErrorAction SilentlyContinue
            Write-Host "Freed port $port (PID $owning)"
        }
    }
} catch {
    Write-Host "(Port $port cleanup skipped: $_)"
}
