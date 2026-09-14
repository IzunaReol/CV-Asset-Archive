$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
docker compose --env-file (Join-Path $projectRoot ".env") -f (Join-Path $projectRoot "deploy\docker-compose.yml") down
