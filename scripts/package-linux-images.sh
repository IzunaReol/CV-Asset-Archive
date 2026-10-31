#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
project_root="$(cd -- "$script_dir/.." && pwd)"
compose_file="$project_root/deploy/docker-compose.yml"
output="${1:-$project_root/../cv-archive-v2.1.0-linux-images.tar}"
output="$(realpath -m -- "$output")"
[[ ! -e "$output" && ! -e "$output.sha256" && ! -e "$output.platform" ]] || { echo "目标文件已存在：$output" >&2; exit 1; }
command -v docker >/dev/null && docker compose version >/dev/null && docker info >/dev/null || { echo "需要可用的 Docker Engine 与 Compose v2。" >&2; exit 1; }
command -v sha256sum >/dev/null || { echo "缺少 sha256sum。" >&2; exit 1; }
mkdir -p -- "$(dirname -- "$output")"

cd -- "$project_root"
docker compose -f "$compose_file" build api worker frontend
docker compose -f "$compose_file" pull mongodb minio redis
mapfile -t images < <(docker compose -f "$compose_file" config --images | sort -u)
((${#images[@]} == 6)) || { echo "预期打包 6 个镜像，实际 ${#images[@]} 个；请检查 Compose 配置。" >&2; exit 1; }
docker image inspect "${images[@]}" >/dev/null
platform="$(docker version --format '{{.Server.Os}}/{{.Server.Arch}}')"
[[ "$platform" == linux/* ]] || { echo "必须使用 Linux 容器引擎构建镜像，当前：$platform" >&2; exit 1; }
for image in "${images[@]}"; do
  actual="$(docker image inspect --format '{{.Os}}/{{.Architecture}}' "$image")"
  [[ "$actual" == "$platform" ]] || { echo "镜像 $image 的平台是 $actual，与构建平台 $platform 不一致。" >&2; exit 1; }
done
trap 'rm -f -- "$output" "$output.sha256" "$output.platform"' ERR
docker save --output "$output" "${images[@]}"
printf '%s\n' "$platform" "${images[@]}" > "$output.platform"
(cd -- "$(dirname -- "$output")" && sha256sum "$(basename -- "$output")" "$(basename -- "$output").platform" > "$(basename -- "$output").sha256")
trap - ERR
echo "镜像包：$output"
echo "校验文件：$output.sha256"
echo "平台：$platform（目标服务器须使用相同架构）"
