param(
    [string]$RegistryPrefix = "auto",
    [switch]$SkipBuild
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$composeFile = Join-Path $projectRoot "deploy\docker-compose.yml"
$envFile = Join-Path $projectRoot ".env"

function Find-DockerDesktop {
    $candidates = @("C:\Program Files\Docker\Docker\Docker Desktop.exe")
    $dockerCommand = Get-Command docker -ErrorAction SilentlyContinue
    if ($dockerCommand) {
        $desktopDirectory = Split-Path -Parent (Split-Path -Parent (Split-Path -Parent $dockerCommand.Source))
        $candidates += Join-Path $desktopDirectory "Docker Desktop.exe"
    }
    $uninstallRoots = @(
        "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\*",
        "HKLM:\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\*",
        "HKCU:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\*"
    )
    $installLocations = Get-ItemProperty $uninstallRoots -ErrorAction SilentlyContinue |
        Where-Object { $_.DisplayName -eq "Docker Desktop" } |
        Select-Object -ExpandProperty InstallLocation -ErrorAction SilentlyContinue
    foreach ($location in $installLocations) {
        if ($location) { $candidates += Join-Path $location "Docker Desktop.exe" }
    }
    return $candidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
}

function Test-DockerEngine {
    $previousPreference = $ErrorActionPreference
    $ErrorActionPreference = "SilentlyContinue"
    docker info *> $null
    $exitCode = $LASTEXITCODE
    $ErrorActionPreference = $previousPreference
    return $exitCode -eq 0
}

if (-not (Test-Path -LiteralPath $envFile)) {
    throw "未找到 .env。首次使用请运行 deploy-windows.cmd 完成部署。"
}

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    throw "未找到 Docker。请先安装 Docker Desktop，或使用离线环境包中的安装说明。"
}

if (-not (Test-DockerEngine)) {
    $dockerDesktop = Find-DockerDesktop
    if (-not (Test-Path -LiteralPath $dockerDesktop)) {
        throw "Docker 引擎未运行，且未找到 Docker Desktop 安装程序。请手动打开 Docker Desktop。"
    }
    Write-Host "正在启动 Docker Desktop：$dockerDesktop" -ForegroundColor Yellow
    Start-Process -FilePath $dockerDesktop -WindowStyle Hidden
    $deadline = (Get-Date).AddMinutes(2)
    do {
        Start-Sleep -Seconds 3
        $dockerReady = Test-DockerEngine
    } until ($dockerReady -or (Get-Date) -ge $deadline)
    if (-not $dockerReady) { throw "Docker 引擎在两分钟内未就绪，请打开 Docker Desktop 查看状态。" }
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
$env:COMPOSE_BAKE = "false"
$env:DOCKER_BUILDKIT = "0"

$mongoContainerId = (& docker compose --env-file $envFile -f $composeFile ps -q mongodb 2>$null).Trim()
if ($mongoContainerId) {
    $mongoHealth = (& docker inspect --format "{{if .State.Health}}{{.State.Health.Status}}{{end}}" $mongoContainerId 2>$null).Trim()
    if ($mongoHealth -eq "unhealthy") {
        Write-Host "检测到 MongoDB 容器健康检查异常，正在保留数据卷并重新创建容器。" -ForegroundColor Yellow
        & docker compose --env-file $envFile -f $composeFile up -d --no-deps --force-recreate mongodb
        if ($LASTEXITCODE -ne 0) { throw "MongoDB 容器恢复失败。" }
    }
}

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

$frontendPortLine = Select-String -LiteralPath $envFile -Pattern '^FRONTEND_PORT=(\d+)$' | Select-Object -Last 1
$frontendPort = if ($frontendPortLine) { $frontendPortLine.Matches[0].Groups[1].Value } else { "8080" }
Write-Host "启动完成，健康检查通过。" -ForegroundColor Green
Write-Host "系统地址：http://localhost:$frontendPort"
