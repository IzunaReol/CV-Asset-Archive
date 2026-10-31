#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
project_root="$(cd -- "$script_dir/.." && pwd)"
env_file="$project_root/.env"
compose_file="$project_root/deploy/docker-compose.yml"
mode="${1:---build}"
[[ "$mode" == --build || "$mode" == --images ]] || { echo "参数应为 --build 或 --images。" >&2; exit 2; }
for tool in docker curl df awk grep ss; do command -v "$tool" >/dev/null || { echo "缺少 $tool。" >&2; exit 1; }; done
docker compose version >/dev/null 2>&1 && docker info >/dev/null 2>&1 || { echo "Docker Engine 或 Compose v2 不可用。" >&2; exit 1; }
[[ -f "$env_file" ]] || { echo "缺少 .env；先运行 deploy-linux.sh。" >&2; exit 1; }
docker compose --env-file "$env_file" -f "$compose_file" config --quiet

env_value() { sed -n "s/^$1=//p" "$env_file" | tail -n 1; }
for key in JWT_SECRET INITIAL_ADMIN_PASSWORD MINIO_ACCESS_KEY MINIO_SECRET_KEY APP_BASE_URL API_BASE_URL; do
  [[ -n "$(env_value "$key")" ]] || { echo ".env 缺少 $key。" >&2; exit 1; }
done
[[ "$(env_value JWT_SECRET)" != replace-with-at-least-32-random-bytes && "$(env_value INITIAL_ADMIN_PASSWORD)" != replace-with-a-strong-password ]] || { echo ".env 仍包含默认凭据。" >&2; exit 1; }

docker_root="$(docker info --format '{{.DockerRootDir}}')"
[[ -d "$docker_root" ]] || { echo "Docker 数据目录不可访问：$docker_root" >&2; exit 1; }
free_kib="$(df -Pk "$docker_root" | awk 'END {print $4}')"
((free_kib >= 2 * 1024 * 1024)) || { echo "项目所在磁盘可用空间不足 2 GiB；请检查镜像与数据盘容量。" >&2; exit 1; }

if [[ "$mode" == --images ]]; then
  mapfile -t images < <(docker compose --env-file "$env_file" -f "$compose_file" config --images | sort -u)
  for image in "${images[@]}"; do
    docker image inspect "$image" >/dev/null 2>&1 || { echo "缺少本地镜像：$image" >&2; exit 1; }
  done
fi

# Only check host ports for a fresh project; occupied ports are expected during a later restart.
if [[ -z "$(docker compose --env-file "$env_file" -f "$compose_file" ps -aq)" ]]; then
  for key in FRONTEND_PORT API_PORT MINIO_API_PORT MINIO_CONSOLE_PORT; do
    case "$key" in FRONTEND_PORT) default=8080;; API_PORT) default=8000;; MINIO_API_PORT) default=9000;; *) default=9001;; esac
    port="$(env_value "$key")"; port="${port:-$default}"
    [[ "$port" =~ ^[0-9]+$ ]] || { echo "$key 必须是数字端口。" >&2; exit 1; }
    if ss -H -ltn "( sport = :$port )" | grep -q .; then
      echo "端口 $port 已被占用（$key）。" >&2; exit 1
    fi
  done
else
  echo "容器已存在，跳过首次部署端口占用检查。"
fi
echo "部署前检查通过：配置、磁盘、Docker$([[ "$mode" == --images ]] && printf '、镜像')。"
