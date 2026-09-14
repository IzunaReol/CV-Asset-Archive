param([Parameter(Mandatory = $true)][string]$Bundle)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$bundlePath = [IO.Path]::GetFullPath($Bundle)
if (-not (Test-Path -LiteralPath $bundlePath)) { throw "离线镜像包不存在：$bundlePath" }
docker load --input $bundlePath
if ($LASTEXITCODE -ne 0) { throw "离线镜像导入失败。" }
& (Join-Path $PSScriptRoot "start.ps1") -RegistryPrefix "" -SkipBuild
