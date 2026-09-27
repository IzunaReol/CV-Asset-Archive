param(
    [string]$RegistryPrefix = "auto",
    [switch]$PrepareOnly
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$envFile = Join-Path $projectRoot ".env"
$envExample = Join-Path $projectRoot ".env.example"

function New-RandomSecret([int]$Bytes = 24) {
    $buffer = New-Object byte[] $Bytes
    $generator = [Security.Cryptography.RandomNumberGenerator]::Create()
    try {
        $generator.GetBytes($buffer)
    } finally {
        $generator.Dispose()
    }
    return -join ($buffer | ForEach-Object { $_.ToString("x2") })
}

function Set-EnvValue([string]$Content, [string]$Name, [string]$Value) {
    $escapedName = [regex]::Escape($Name)
    if ($Content -match "(?m)^$escapedName=") {
        return [regex]::Replace($Content, "(?m)^$escapedName=.*$", "$Name=$Value")
    }
    return $Content.TrimEnd() + [Environment]::NewLine + "$Name=$Value" + [Environment]::NewLine
}

if (-not (Test-Path -LiteralPath $envFile)) {
    if (-not (Test-Path -LiteralPath $envExample)) { throw "缺少 .env.example。" }
    $content = Get-Content -LiteralPath $envExample -Raw -Encoding UTF8
    $adminPassword = New-RandomSecret 12
    $content = Set-EnvValue $content "JWT_SECRET" (New-RandomSecret 32)
    $content = Set-EnvValue $content "INITIAL_ADMIN_PASSWORD" $adminPassword
    $content = Set-EnvValue $content "MINIO_ACCESS_KEY" ("cvarchive" + (New-RandomSecret 6))
    $content = Set-EnvValue $content "MINIO_SECRET_KEY" (New-RandomSecret 24)
    [IO.File]::WriteAllText(
        $envFile,
        $content,
        (New-Object Text.UTF8Encoding($false))
    )
    Write-Host "已创建安全配置 .env。" -ForegroundColor Green
    Write-Host "首次登录账号：admin" -ForegroundColor Yellow
    Write-Host "首次登录密码：$adminPassword" -ForegroundColor Yellow
    Write-Host "请立即保存密码；后续可在 .env 中查看或修改。" -ForegroundColor Yellow
} else {
    $content = Get-Content -LiteralPath $envFile -Raw -Encoding UTF8
    $updated = $false
    $adminPassword = $null
    $credentialRules = @(
        @{ Name = "JWT_SECRET"; Unsafe = @("replace-with-at-least-32-random-bytes"); Value = (New-RandomSecret 32) },
        @{ Name = "INITIAL_ADMIN_PASSWORD"; Unsafe = @("replace-with-a-strong-password", "admin"); Value = (New-RandomSecret 12) },
        @{ Name = "MINIO_ACCESS_KEY"; Unsafe = @("replace-me", "minioadmin"); Value = ("cvarchive" + (New-RandomSecret 6)) },
        @{ Name = "MINIO_SECRET_KEY"; Unsafe = @("replace-me", "minioadmin"); Value = (New-RandomSecret 24) }
    )
    foreach ($rule in $credentialRules) {
        $escapedName = [regex]::Escape($rule.Name)
        $match = [regex]::Match($content, "(?m)^$escapedName=(.*)$")
        if (-not $match.Success -or $rule.Unsafe -contains $match.Groups[1].Value.Trim()) {
            $content = Set-EnvValue $content $rule.Name $rule.Value
            $updated = $true
            if ($rule.Name -eq "INITIAL_ADMIN_PASSWORD") { $adminPassword = $rule.Value }
        }
    }
    if ($updated) {
        [IO.File]::WriteAllText(
            $envFile,
            $content,
            (New-Object Text.UTF8Encoding($false))
        )
        Write-Host "已替换 .env 中缺失或不安全的默认凭据。" -ForegroundColor Yellow
        if ($adminPassword) {
            Write-Host "新的首次登录密码：$adminPassword" -ForegroundColor Yellow
        }
    } else {
        Write-Host "检测到现有 .env，将保留原配置和数据连接。"
    }
}

if ($PrepareOnly) {
    Write-Host "配置准备完成，未启动服务。"
    return
}

& (Join-Path $PSScriptRoot "start.ps1") -RegistryPrefix $RegistryPrefix
