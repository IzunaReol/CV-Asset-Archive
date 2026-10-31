#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
project_root="$(cd -- "$script_dir/.." && pwd)"
env_file="$project_root/.env"
env_example="$project_root/.env.example"
prepare_only=false
bundle=""

if [[ "${1:-}" == "--prepare-only" ]]; then
  prepare_only=true
  shift
fi
if [[ "${1:-}" == "--bundle" ]]; then
  (($# >= 2)) || { echo "--bundle 需要镜像包路径。" >&2; exit 2; }
  bundle="$2"
  shift 2
fi
if (($# > 0)); then echo "不支持的参数：$*" >&2; exit 2; fi

random_secret() {
  local bytes="${1:-24}"
  od -An -N "$bytes" -tx1 /dev/urandom | tr -d ' \n'
}

set_env_value() {
  local name="$1"
  local value="$2"
  local temporary
  temporary="$(mktemp "${env_file}.XXXXXX")"
  awk -v name="$name" -v value="$value" '
    BEGIN { replaced = 0 }
    $0 ~ "^" name "=" { print name "=" value; replaced = 1; next }
    { print }
    END { if (!replaced) print name "=" value }
  ' "$env_file" > "$temporary"
  chmod --reference="$env_file" "$temporary" 2>/dev/null || true
  mv -f -- "$temporary" "$env_file"
}

if [[ ! -f "$env_file" ]]; then
  [[ -f "$env_example" ]] || { echo "缺少 .env.example。" >&2; exit 1; }
  cp -- "$env_example" "$env_file"
  admin_password="$(random_secret 12)"
  set_env_value "JWT_SECRET" "$(random_secret 32)"
  set_env_value "INITIAL_ADMIN_PASSWORD" "$admin_password"
  set_env_value "MINIO_ACCESS_KEY" "cvarchive$(random_secret 6)"
  set_env_value "MINIO_SECRET_KEY" "$(random_secret 24)"
  chmod 600 "$env_file"
  echo "已创建安全配置 .env。"
  echo "首次登录账号：admin"
  echo "首次登录密码：$admin_password"
  echo "请立即保存密码；后续可在 .env 中查看或修改。"
else
  updated=false
  admin_password=""
  current_value() {
    sed -n "s/^$1=//p" "$env_file" | tail -n 1
  }
  replace_if_unsafe() {
    local name="$1"
    local value="$2"
    shift 2
    local current
    current="$(current_value "$name")"
    if [[ -z "$current" ]]; then
      set_env_value "$name" "$value"
      updated=true
      return
    fi
    local unsafe
    for unsafe in "$@"; do
      if [[ "$current" == "$unsafe" ]]; then
        set_env_value "$name" "$value"
        updated=true
        return
      fi
    done
  }
  replace_if_unsafe "JWT_SECRET" "$(random_secret 32)" "replace-with-at-least-32-random-bytes"
  generated_admin_password="$(random_secret 12)"
  previous_admin_password="$(current_value INITIAL_ADMIN_PASSWORD)"
  replace_if_unsafe "INITIAL_ADMIN_PASSWORD" "$generated_admin_password" "replace-with-a-strong-password" "admin"
  if [[ "$previous_admin_password" != "$(current_value INITIAL_ADMIN_PASSWORD)" ]]; then
    admin_password="$generated_admin_password"
  fi
  replace_if_unsafe "MINIO_ACCESS_KEY" "cvarchive$(random_secret 6)" "replace-me" "minioadmin"
  replace_if_unsafe "MINIO_SECRET_KEY" "$(random_secret 24)" "replace-me" "minioadmin"
  if [[ "$updated" == true ]]; then
    chmod 600 "$env_file"
    echo "已替换 .env 中缺失或不安全的默认凭据。"
    if [[ -n "$admin_password" ]]; then
      echo "新的首次登录密码：$admin_password"
    fi
  else
    echo "检测到现有 .env，将保留原配置和数据连接。"
  fi
fi

if [[ "$prepare_only" == true ]]; then
  echo "配置准备完成，未启动服务。"
  exit 0
fi

if [[ -n "$bundle" ]]; then
  bundle="$(realpath -- "$bundle")"
  [[ -f "$bundle" && -f "$bundle.sha256" && -f "$bundle.platform" ]] || { echo "镜像包及其 .sha256、.platform 文件必须同时存在。" >&2; exit 1; }
  command -v sha256sum >/dev/null || { echo "缺少 sha256sum。" >&2; exit 1; }
  (cd -- "$(dirname -- "$bundle")" && sha256sum -c "$(basename -- "$bundle").sha256")
  local_platform="$(docker version --format '{{.Server.Os}}/{{.Server.Arch}}')"
  bundle_platform="$(head -n 1 -- "$bundle.platform")"
  [[ "$local_platform" == "$bundle_platform" ]] || { echo "镜像包架构与当前 Docker 引擎不一致。" >&2; exit 1; }
  compose_file="$project_root/deploy/docker-compose.yml"
  if ! diff -u <(tail -n +2 -- "$bundle.platform" | sort -u) <(docker compose --env-file "$env_file" -f "$compose_file" config --images | sort -u); then
    echo "镜像包与当前 Compose 镜像名不匹配；请核对 APP_IMAGE_TAG、DOCKER_REGISTRY_PREFIX 和 MINIO_IMAGE。" >&2; exit 1
  fi
  docker load --input "$bundle"
  exec "$script_dir/start.sh" --images
fi
exec "$script_dir/start.sh" --build
