#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
project_root="$(cd -- "$script_dir/.." && pwd)"
compose_file="$project_root/deploy/docker-compose.yml"
env_file="$project_root/.env"
build=false

if [[ "${1:-}" == "--build" ]]; then
  build=true
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

compose_args=(compose --env-file "$env_file" -f "$compose_file" up -d)
if [[ "$build" == true ]]; then
  compose_args+=(--build)
else
  compose_args+=(--no-build)
fi
docker "${compose_args[@]}"

deadline=$((SECONDS + 180))
until curl --fail --silent --show-error --max-time 5 http://localhost:8000/health/ready >/dev/null 2>&1; do
  if ((SECONDS >= deadline)); then
    docker compose --env-file "$env_file" -f "$compose_file" ps
    echo "服务未在三分钟内通过健康检查。" >&2
    exit 1
  fi
  sleep 3
done

admin_username="$(sed -n 's/^INITIAL_ADMIN_USERNAME=//p' "$env_file" | tail -n 1)"
echo "启动完成。"
echo "系统地址：http://localhost:8080"
echo "登录账号：${admin_username:-admin}"
