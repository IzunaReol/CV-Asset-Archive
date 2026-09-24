param(
    [string]$FallbackProxy = "http://127.0.0.1:7890"
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$runtime = Join-Path $root ".runtime"
$downloads = Join-Path $runtime "downloads"
$apps = Join-Path $runtime "apps"

function Require-Command([string]$Name, [string]$Help) {
    if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) { throw "$Name is required. $Help" }
}

function Require-Version([string]$Name, [version]$Minimum, [string]$Help) {
    Require-Command $Name $Help
    $rawVersion = (& $Name --version | Select-Object -First 1).Trim()
    if ($rawVersion -notmatch '(\d+\.\d+\.\d+)') { throw "Cannot determine the $Name version: $rawVersion" }
    $currentVersion = [version]$Matches[1]
    if ($currentVersion -lt $Minimum) {
        throw "$Name $Minimum or newer is required; found $currentVersion. $Help"
    }
}

function Download-File([string]$Url, [string]$Destination, [string]$Sha256) {
    if ((Test-Path -LiteralPath $Destination) -and (Get-Item -LiteralPath $Destination).Length -gt 0) {
        $currentHash = (Get-FileHash -LiteralPath $Destination -Algorithm SHA256).Hash
        if ($currentHash -eq $Sha256) {
            Write-Host "Using verified download: $Destination"
            return
        }
        Remove-Item -LiteralPath $Destination -Force
    }
    $partial = "$Destination.part"
    $common = @("-L", "--fail", "--retry", "3", "--connect-timeout", "20", "--ssl-no-revoke", "-C", "-", "-o", $partial, $Url)
    Write-Host "Downloading $Url"
    & curl.exe @common
    if ($LASTEXITCODE -ne 0) {
        if ([string]::IsNullOrWhiteSpace($FallbackProxy)) { throw "Download failed: $Url" }
        Write-Host "Direct download failed. Retrying through $FallbackProxy"
        & curl.exe "-L" "--fail" "--retry" "3" "--connect-timeout" "20" "--ssl-no-revoke" "--proxy" $FallbackProxy "-C" "-" "-o" $partial $Url
        if ($LASTEXITCODE -ne 0) { throw "Download failed: $Url" }
    }
    $downloadHash = (Get-FileHash -LiteralPath $partial -Algorithm SHA256).Hash
    if ($downloadHash -ne $Sha256) { throw "Checksum mismatch: $Url" }
    Move-Item -LiteralPath $partial -Destination $Destination -Force
}

Require-Command "curl.exe" "Use Windows 11 or install curl."
Require-Version "python.exe" ([version]"3.12.0") "Install Python 3.12 or newer."
Require-Version "node.exe" ([version]"22.20.0") "Install Node.js 22.20 or newer."
Require-Command "npm.cmd" "Install Node.js 22.20 or newer."

New-Item -ItemType Directory -Force -Path $downloads, $apps | Out-Null
$mongoZip = Join-Path $downloads "mongodb-8.0.28.zip"
$redisZip = Join-Path $downloads "redis-8.10.1-cygwin.zip"
$minioExe = Join-Path $downloads "minio-2025-09-07.exe"

Download-File "https://fastdl.mongodb.org/windows/mongodb-windows-x86_64-8.0.28.zip" $mongoZip "A6573419FC1D8767B7A86911C4A1B832FA408D4B8BD32D281F049B87A30073CF"
Download-File "https://github.com/minio/minio/releases/download/RELEASE.2025-09-07T16-13-09Z/minio.windows-amd64.RELEASE.2025-09-07T16-13-09Z.exe" $minioExe "AF709E6BA68488404E85ACDD22A3030D0F5E56A108D4B27D744F18CEB50861B4"
Download-File "https://github.com/redis-windows/redis-windows/releases/download/8.10.1/Redis-8.10.1-Windows-x64-cygwin.zip" $redisZip "5532F2CC38A0185556B648D25A0C2FF1CC58029F37FD76ECEB38736976DCB056"

if (-not (Get-ChildItem (Join-Path $apps "mongodb") -Filter mongod.exe -Recurse -ErrorAction SilentlyContinue)) {
    New-Item -ItemType Directory -Force (Join-Path $apps "mongodb") | Out-Null
    Expand-Archive -LiteralPath $mongoZip -DestinationPath (Join-Path $apps "mongodb") -Force
}
if (-not (Get-ChildItem (Join-Path $apps "redis") -Filter redis-server.exe -Recurse -ErrorAction SilentlyContinue)) {
    New-Item -ItemType Directory -Force (Join-Path $apps "redis") | Out-Null
    Expand-Archive -LiteralPath $redisZip -DestinationPath (Join-Path $apps "redis") -Force
}
New-Item -ItemType Directory -Force (Join-Path $apps "minio") | Out-Null
Copy-Item -LiteralPath $minioExe -Destination (Join-Path $apps "minio\minio.exe") -Force

$venvPython = Join-Path $runtime "venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $venvPython)) { python -m venv (Join-Path $runtime "venv") }
$env:PIP_CACHE_DIR = Join-Path $runtime "pip-cache"
& $venvPython -m pip install --disable-pip-version-check -e (Join-Path $root "backend") -e (Join-Path $root "worker")
if ($LASTEXITCODE -ne 0) { throw "Python dependency installation failed." }

Push-Location (Join-Path $root "frontend")
try {
    & npm.cmd ci
    if ($LASTEXITCODE -ne 0) { throw "Frontend dependency installation failed." }
} finally {
    Pop-Location
}

Write-Host "Native runtime installed under $runtime" -ForegroundColor Green
Write-Host "No Windows service or system setting was changed."
