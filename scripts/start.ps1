param(
    [string]$RegistryPrefix = "auto",
    [switch]$SkipBuild
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$composeFile = Join-Path $projectRoot "deploy\docker-compose.yml"
$envFile = Join-Path $projectRoot ".env"
$dockerDesktop = "C:\Program Files\Docker\Docker\Docker Desktop.exe"

if (-not (Test-Path -LiteralPath $envFile)) {
    throw "未找到 .env。首次使用请运行 deploy-windows.cmd 完成部署。"
}

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    throw "未找到 Docker。请先安装 Docker Desktop，或使用离线环境包中的安装说明。"
}

docker info *> $null
if ($LASTEXITCODE -ne 0) {
    if (-not (Test-Path -LiteralPath $dockerDesktop)) {
        throw "Docker 引擎未运行。"
    }
    Start-Process -FilePath $dockerDesktop -WindowStyle Hidden
    $deadline = (Get-Date).AddMinutes(2)
    do {
        Start-Sleep -Seconds 3
        docker info *> $null
    } until ($LASTEXITCODE -eq 0 -or (Get-Date) -ge $deadline)
    if ($LASTEXITCODE -ne 0) { throw "Docker 引擎在两分钟内未就绪，请打开 Docker Desktop 查看状态。" }
}

if ($RegistryPrefix -eq "auto") {
    if ($SkipBuild) {
        $RegistryPrefix = ""
    } else {
        try {
            Invoke-WebRequest -UseBasicParsing -Uri "https://auth.docker.io/token?scope=repository%3Alibrary%2Fredis%3Apull&service=registry.docker.io" -TimeoutSec 8 | Out-Null
            $RegistryPrefix = ""
        } catch {
            $RegistryPrefix = "docker.m.daocloud.io/"
            Write-Host "Docker Hub 不可达，改用 DaoCloud 公共镜像代理。" -ForegroundColor Yellow
        }
    }
}

$env:DOCKER_REGISTRY_PREFIX = $RegistryPrefix
$arguments = @("compose", "--env-file", $envFile, "-f", $composeFile, "up", "-d")
if (-not $SkipBuild) { $arguments += "--build" }
& docker @arguments
if ($LASTEXITCODE -ne 0) { throw "容器启动失败。" }

$deadline = (Get-Date).AddMinutes(3)
do {
    Start-Sleep -Seconds 3
    try { $health = Invoke-RestMethod -Uri "http://localhost:8000/health/ready" -TimeoutSec 5 } catch { $health = $null }
} until ($health.status -eq "ok" -or (Get-Date) -ge $deadline)
if ($health.status -ne "ok") {
    docker compose --env-file $envFile -f $composeFile ps
    throw "服务未在三分钟内通过健康检查。"
}

Write-Host "启动完成，健康检查通过。" -ForegroundColor Green
Write-Host "系统地址：http://localhost:8080"
