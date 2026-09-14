param([string]$Output = "cv-archive-offline-images.tar")

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$composeFile = Join-Path $projectRoot "deploy\docker-compose.yml"
$envFile = Join-Path $projectRoot ".env"
$outputPath = [IO.Path]::GetFullPath((Join-Path $projectRoot $Output))
$images = docker compose --env-file $envFile -f $composeFile config --images | Sort-Object -Unique
if (-not $images) { throw "没有找到可导出的镜像。" }
docker image inspect $images *> $null
if ($LASTEXITCODE -ne 0) { throw "部分镜像尚未构建，请先运行 scripts\start.ps1。" }
docker save --output $outputPath $images
if ($LASTEXITCODE -ne 0) { throw "离线镜像包导出失败。" }
Write-Host "离线镜像包已生成：$outputPath" -ForegroundColor Green
