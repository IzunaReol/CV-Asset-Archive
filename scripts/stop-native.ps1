$ErrorActionPreference = "Continue"
$root = Split-Path -Parent $PSScriptRoot
$pids = Join-Path $root ".runtime\pids"
foreach ($name in @("frontend", "worker", "api", "redis", "minio", "mongodb")) {
    $pidFile = Join-Path $pids "$name.pid"
    if (-not (Test-Path -LiteralPath $pidFile)) { continue }
    $processId = [int](Get-Content -LiteralPath $pidFile -Raw)
    $process = Get-Process -Id $processId -ErrorAction SilentlyContinue
    if ($process) {
        Stop-Process -Id $processId -Force
        Write-Host "$name stopped."
    }
    Remove-Item -LiteralPath $pidFile -Force -ErrorAction SilentlyContinue
}
