$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$runtime = Join-Path $root ".runtime"
$apps = Join-Path $runtime "apps"
$data = Join-Path $runtime "data"
$logs = Join-Path $runtime "logs"
$pids = Join-Path $runtime "pids"

New-Item -ItemType Directory -Force -Path $data, $logs, $pids | Out-Null

function Require-File([string]$Path, [string]$Name) {
    if ([string]::IsNullOrWhiteSpace($Path) -or -not (Test-Path -LiteralPath $Path)) {
        throw "$Name is not installed in .runtime. Run the native environment installer first."
    }
}

function Quote-Argument([string]$Value) {
    return '"' + $Value.Replace('"', '\"') + '"'
}

function Start-ManagedProcess([string]$Name, [string]$FilePath, [string[]]$Arguments, [string]$WorkingDirectory) {
    $pidFile = Join-Path $pids "$Name.pid"
    if (Test-Path -LiteralPath $pidFile) {
        $oldPid = [int](Get-Content -LiteralPath $pidFile -Raw)
        if (Get-Process -Id $oldPid -ErrorAction SilentlyContinue) {
            Write-Host "$Name already running (PID $oldPid)."
            return
        }
    }
    $stdout = Join-Path $logs "$Name.out.log"
    $stderr = Join-Path $logs "$Name.err.log"
    $process = Start-Process -FilePath $FilePath -ArgumentList $Arguments -WorkingDirectory $WorkingDirectory -WindowStyle Hidden -RedirectStandardOutput $stdout -RedirectStandardError $stderr -PassThru
    Set-Content -LiteralPath $pidFile -Value $process.Id -Encoding ASCII
    Start-Sleep -Milliseconds 500
    if ($process.HasExited) { throw "$Name exited during startup. Check $stderr" }
    Write-Host "$Name started (PID $($process.Id))."
}

$mongo = Get-ChildItem -Path (Join-Path $apps "mongodb") -Filter mongod.exe -Recurse -ErrorAction SilentlyContinue | Select-Object -First 1
$minio = Join-Path $apps "minio\minio.exe"
$redis = Get-ChildItem -Path (Join-Path $apps "redis") -Filter redis-server.exe -Recurse -ErrorAction SilentlyContinue | Select-Object -First 1
$python = Join-Path $runtime "venv\Scripts\python.exe"
$node = (Get-Command node.exe -ErrorAction SilentlyContinue).Source
$vite = Join-Path $root "frontend\node_modules\vite\bin\vite.js"
Require-File $(if ($mongo) { $mongo.FullName } else { $null }) "MongoDB"
Require-File $minio "MinIO"
Require-File $(if ($redis) { $redis.FullName } else { $null }) "Redis"
Require-File $python "Python environment"
Require-File $node "Node.js"
Require-File $vite "Frontend dependencies"

$env:MONGODB_URI = "mongodb://127.0.0.1:27017"
$env:MONGODB_DATABASE = "cv_archive"
$env:MINIO_ENDPOINT = "127.0.0.1:9000"
$env:MINIO_PUBLIC_ENDPOINT = "localhost:9000"
$env:MINIO_ACCESS_KEY = "minioadmin"
$env:MINIO_SECRET_KEY = "minioadmin"
$env:MINIO_BUCKET = "cv-assets"
$env:STORAGE_DATA_PATH = Join-Path $data "minio"
$env:REDIS_URL = "redis://127.0.0.1:6379/0"
$env:WORKER_TEMP_DIR = Join-Path $runtime "temp"
$env:APP_BASE_URL = "http://localhost:5173"
$env:API_BASE_URL = "http://localhost:8000/api/v1"
$env:INITIAL_ADMIN_USERNAME = "admin"
$env:INITIAL_ADMIN_PASSWORD = "admin"
$env:MAX_UPLOAD_SIZE_BYTES = "10737418240"
$env:MINIO_ROOT_USER = "minioadmin"
$env:MINIO_ROOT_PASSWORD = "minioadmin"

New-Item -ItemType Directory -Force -Path (Join-Path $data "mongodb"), (Join-Path $data "minio"), (Join-Path $data "redis"), $env:WORKER_TEMP_DIR | Out-Null
Start-ManagedProcess "mongodb" $mongo.FullName @("--dbpath", (Quote-Argument (Join-Path $data "mongodb")), "--bind_ip", "127.0.0.1", "--port", "27017") $root
Start-ManagedProcess "minio" $minio @("server", (Quote-Argument (Join-Path $data "minio")), "--address", "127.0.0.1:9000", "--console-address", "127.0.0.1:9001") $root
Start-ManagedProcess "redis" $redis.FullName @("--bind", "127.0.0.1", "--port", "6379", "--dir", (Quote-Argument (Join-Path $data "redis")), "--appendonly", "yes") $root

Start-Sleep -Seconds 2
Start-ManagedProcess "api" $python @("-m", "uvicorn", "backend.app.main:app", "--host", "127.0.0.1", "--port", "8000") $root
Start-ManagedProcess "worker" $python @("-m", "celery", "-A", "worker.tasks", "worker", "--pool=solo", "--loglevel=INFO") $root
Start-ManagedProcess "frontend" $node @((Quote-Argument $vite), "--host", "127.0.0.1", "--port", "5173") (Join-Path $root "frontend")

$deadline = (Get-Date).AddMinutes(2)
do {
    Start-Sleep -Seconds 2
    try { $health = Invoke-RestMethod -Uri "http://localhost:8000/health/ready" -TimeoutSec 3 } catch { $health = $null }
} until ($null -ne $health -or (Get-Date) -ge $deadline)
if ($null -eq $health) { throw "Services did not become ready. Check .runtime\logs." }

$body = @{ username = "admin"; password = "admin" } | ConvertTo-Json
$login = Invoke-RestMethod -Method Post -Uri "http://localhost:8000/api/v1/auth/login" -ContentType "application/json" -Body $body
if (-not $login.access_token) { throw "Admin login check failed." }
Write-Host "Ready: http://localhost:5173" -ForegroundColor Green
Write-Host "Login: admin / admin"
