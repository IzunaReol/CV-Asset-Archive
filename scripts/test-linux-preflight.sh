#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
temp="$(mktemp -d)"
trap 'rm -rf -- "$temp"' EXIT
mkdir -p "$temp/project/scripts" "$temp/project/deploy" "$temp/bin"
cp "$script_dir/preflight-linux.sh" "$temp/project/scripts/"
cp "$script_dir/../deploy/docker-compose.yml" "$temp/project/deploy/"
cat > "$temp/project/.env" <<'EOF'
JWT_SECRET=test-secret
INITIAL_ADMIN_PASSWORD=test-password
MINIO_ACCESS_KEY=test-user
MINIO_SECRET_KEY=test-secret
APP_BASE_URL=http://localhost:8180
API_BASE_URL=http://localhost:8000/api/v1
FRONTEND_PORT=8180
API_PORT=8000
EOF
cat > "$temp/bin/docker" <<'EOF'
#!/usr/bin/env bash
case "$*" in
  'compose version') exit 0;;
  'info') exit 0;;
  "info --format {{.DockerRootDir}}") printf '%s\n' /tmp; exit 0;;
  *'config --quiet'|*'ps -aq') exit 0;;
  *'config --images') printf '%s\n' image-1 image-2;;
  'image inspect image-2') [[ "${MISSING_IMAGE:-}" != 1 ]]; exit;;
  'image inspect image-1') exit 0;;
  *) echo "unexpected docker command: $*" >&2; exit 1;;
esac
EOF
cat > "$temp/bin/ss" <<'EOF'
#!/usr/bin/env bash
[[ "${OCCUPIED_PORT:-}" == 8180 && "$*" == *':8180'* ]] && echo occupied
exit 0
EOF
printf '#!/usr/bin/env bash\nexit 0\n' > "$temp/bin/curl"
chmod +x "$temp/bin/docker" "$temp/bin/ss" "$temp/bin/curl"
export PATH="$temp/bin:$PATH"
bash "$temp/project/scripts/preflight-linux.sh" --images >/dev/null
if MISSING_IMAGE=1 bash "$temp/project/scripts/preflight-linux.sh" --images >/dev/null 2>&1; then
  echo "缺失镜像时应阻断部署。" >&2; exit 1
fi
if OCCUPIED_PORT=8180 bash "$temp/project/scripts/preflight-linux.sh" --images >/dev/null 2>&1; then
  echo "首次部署端口被占用时应阻断部署。" >&2; exit 1
fi
echo "Linux 首次部署预检查测试通过。"
