# 部署说明

## 使用条件

- Windows：Docker Desktop 和 Docker Compose v2。
- Linux：Docker Engine、Docker Compose v2、Bash、curl、`od`。
- 默认占用 Web `8080`、API `8000`、MinIO `9000/9001` 端口。

## Windows 一键部署与启动

首次部署时双击仓库根目录的 `deploy-windows.cmd`，或在终端运行：

```powershell
.\deploy-windows.cmd
```

脚本会检查 Docker，必要时启动 Docker Desktop；首次创建 `.env` 时自动生成 JWT、管理员密码和 MinIO 凭据，然后构建镜像、启动服务并完成健康检查。已有 `.env` 时保留有效配置，仅替换缺失或明显不安全的默认凭据。

部署完成后的日常启动不重新构建镜像：

```powershell
.\start-windows.cmd
```

需要重新构建时再次运行 `deploy-windows.cmd`。停止服务：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\stop.ps1
```

## Linux 一键部署与启动

首次部署：

```bash
bash deploy-linux.sh
```

脚本会检查 Docker Engine、Docker Compose v2、Bash、curl 和 `od`；首次创建 `.env` 时自动生成 JWT、管理员密码和 MinIO 凭据，并把配置权限设为仅当前用户可读写。已有 `.env` 时保留有效配置，仅替换缺失或明显不安全的默认凭据。

部署完成后的日常启动不重新构建镜像：

```bash
bash start-linux.sh
```

需要重新构建时再次运行 `bash deploy-linux.sh`。停止服务：

```bash
docker compose --env-file .env -f deploy/docker-compose.yml down
```

不要在需要保留数据时使用 `down -v`。

## 首次部署结果

首次生成 `.env` 时，部署脚本会在终端显示随机管理员密码。请立即保存；后续也可在服务器本地 `.env` 的 `INITIAL_ADMIN_PASSWORD` 中查看。`.env` 不应提交到 Git。

默认地址：

- Web：`http://localhost:8080`
- API：`http://localhost:8000`
- API 文档：`http://localhost:8000/docs`
- 就绪检查：`http://localhost:8000/health/ready`
- MinIO 控制台：`http://localhost:9001`

从其他电脑访问时，将 `.env` 中的 `APP_BASE_URL`、`API_BASE_URL` 和 `MINIO_PUBLIC_ENDPOINT` 改为客户端可访问的域名或主机地址。外部通过 HTTPS 访问时设置 `MINIO_PUBLIC_SECURE=true`。修改配置后重新运行对应系统的部署脚本。

## Windows 本机模式

不使用 Docker 时，Windows 可以执行根目录的 `install-native.cmd`、`start-native.cmd` 和 `stop-native.cmd`。本机运行依赖、数据和日志全部位于 `.runtime`，不会安装 Windows 服务。

## 离线部署

联网电脑导出镜像：

```powershell
powershell -ExecutionPolicy Bypass -File scripts/export-offline.ps1
```

目标电脑导入并启动：

```powershell
powershell -ExecutionPolicy Bypass -File scripts/import-offline.ps1 -Bundle cv-archive-offline-images.tar
```

## 发布前检查

1. 验证 `/health/ready` 返回 MongoDB、MinIO、Redis 全部正常。
2. 验证登录、上传、预览、后台任务、回收站和导出。
3. 使用 `python scripts/compose-backup.py backup <仓库外目录>` 备份，并在独立环境演练恢复。
4. 记录版本、配置变化和回滚步骤。

升级、备份和数据治理要求见 `docs/operations.md` 与 `docs/migrations.md`。
