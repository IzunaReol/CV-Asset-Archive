#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
project_root="$(cd -- "$script_dir/.." && pwd)"
compose_file="$project_root/deploy/docker-compose.yml"
env_file="$project_root/.env"
build=false
images=false

if [[ "${1:-}" == "--build" ]]; then
  build=true
  shift
fi
if [[ "${1:-}" == "--images" ]]; then
  images=true
  shift
fi
if (($# > 0)); then
  echo "不支持的参数：$*" >&2
  exit 2
fi

command -v docker >/dev/null 2>&1 || { echo "未找到 Docker，请先安装 Docker Engine。" >&2; exit 1; }
docker compose version >/dev/null 2>&1 || { echo "未找到 Docker Compose v2。" >&2; exit 1; }
docker info >/dev/null 2>&1 || { echo "Docker 引擎未运行或当前用户无访问权限。" >&2; exit 1; }
command -v curl >/dev/null 2>&1 || { echo "未找到 curl，无法执行服务健康检查。" >&2; exit 1; }
[[ -f "$env_file" ]] || { echo "未找到 .env，首次使用请运行 ./deploy-linux.sh。" >&2; exit 1; }

if [[ "$build" == true ]]; then
  "$script_dir/preflight-linux.sh" --build
else
  "$script_dir/preflight-linux.sh" --images
fi

env_value() { sed -n "s/^$1=//p" "$env_file" | tail -n 1; }
api_port="$(env_value API_PORT)"; api_port="${api_port:-8000}"
frontend_port="$(env_value FRONTEND_PORT)"; frontend_port="${frontend_port:-8080}"
api_url="http://127.0.0.1:$api_port"
frontend_url="http://127.0.0.1:$frontend_port"
expected_version="$(sed -n 's/^version = "\([^"]*\)"/\1/p' "$project_root/backend/pyproject.toml" | head -n 1)"

mongo_container_id="$(docker compose --env-file "$env_file" -f "$compose_file" ps -q mongodb 2>/dev/null || true)"
if [[ -n "$mongo_container_id" ]]; then
  mongo_health="$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{end}}' "$mongo_container_id" 2>/dev/null || true)"
  if [[ "$mongo_health" == "unhealthy" ]]; then
    echo "检测到 MongoDB 容器健康检查异常，正在保留数据卷并重新创建容器。"
    docker compose --env-file "$env_file" -f "$compose_file" up -d --no-deps --force-recreate mongodb
  fi
fi

compose_args=(compose --env-file "$env_file" -f "$compose_file" up -d)
if [[ "$build" == true ]]; then
  compose_args+=(--build)
else
  compose_args+=(--no-build --pull never)
fi
docker "${compose_args[@]}"

deadline=$((SECONDS + 180))
until curl --fail --silent --max-time 5 "$api_url/health/ready" >/dev/null 2>&1; do
  if ((SECONDS >= deadline)); then
    docker compose --env-file "$env_file" -f "$compose_file" ps
    echo "服务未在三分钟内通过健康检查。" >&2
    exit 1
  fi
  sleep 3
done

curl --fail --silent --max-time 5 "$frontend_url/" >/dev/null || { echo "前端页面无法访问：$frontend_url" >&2; exit 1; }
openapi="$(curl --fail --silent --max-time 5 "$api_url/openapi.json")"
printf '%s' "$openapi" | grep -Eq '"version"[[:space:]]*:[[:space:]]*"'"$expected_version"'"' || { echo "API 运行版本与仓库版本 $expected_version 不一致。" >&2; exit 1; }
for service in frontend api worker mongodb minio redis; do
  container="$(docker compose --env-file "$env_file" -f "$compose_file" ps -q "$service")"
  [[ -n "$container" && "$(docker inspect --format '{{.State.Running}}' "$container")" == true ]] || { echo "服务未运行：$service" >&2; exit 1; }
done

admin_username="$(sed -n 's/^INITIAL_ADMIN_USERNAME=//p' "$env_file" | tail -n 1)"
app_base_url="$(env_value APP_BASE_URL)"
echo "部署验收通过：6 个容器运行，API 就绪，前端可访问，API 版本 $expected_version。"
echo "系统地址：${app_base_url:-$frontend_url}"
echo "本机检查地址：$frontend_url"
echo "登录账号：${admin_username:-admin}"
