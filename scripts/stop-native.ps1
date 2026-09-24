$ErrorActionPreference = "Continue"
$root = Split-Path -Parent $PSScriptRoot
$pids = Join-Path $root ".runtime\pids"
foreach ($name in @("frontend", "worker", "api", "redis", "minio", "mongodb")) {
    $pidFile = Join-Path $pids "$name.pid"
    if (-not (Test-Path -LiteralPath $pidFile)) { continue }
    $processId = [int](Get-Content -LiteralPath $pidFile -Raw)
    $process = Get-Process -Id $processId -ErrorAction SilentlyContinue
    if ($process) {
        $expectedNames = @{
            frontend = @("node")
            worker = @("python")
            api = @("python")
            redis = @("redis-server")
            minio = @("minio")
            mongodb = @("mongod")
        }
        if ($expectedNames[$name] -contains $process.ProcessName) {
            Stop-Process -Id $processId -Force
            Write-Host "$name stopped."
        } else {
            Write-Warning "$name PID file points to another process (PID $processId, $($process.ProcessName)); it was not stopped."
        }
    }
    Remove-Item -LiteralPath $pidFile -Force -ErrorAction SilentlyContinue
}
