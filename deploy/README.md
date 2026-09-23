# 部署说明

## Linux / Docker Compose

要求 Docker Engine 和 Docker Compose v2。首次部署：

```bash
cp .env.example .env
# 修改 JWT_SECRET、管理员密码和 MinIO 凭据
docker compose -f deploy/docker-compose.yml up --build -d
docker compose -f deploy/docker-compose.yml ps
```

Web 使用 `8080`，API 使用 `8000`，MinIO API 和控制台使用 `9000/9001`。MongoDB、MinIO 和 Redis 数据保存在命名卷中。

从其他电脑访问时，将 `.env` 中的 `MINIO_PUBLIC_ENDPOINT` 设为浏览器可访问的 MinIO 地址（域名或主机 IP 加端口），不要保留 `localhost:9000`。外部通过 HTTPS 访问时设置 `MINIO_PUBLIC_SECURE=true`，内部 MinIO 连接仍可保持 HTTP。API、Worker 和 MinIO 使用同一组 `MINIO_ACCESS_KEY`、`MINIO_SECRET_KEY`。修改后用 `docker compose -f deploy/docker-compose.yml config` 检查配置，再重建服务。

停止服务：

```bash
docker compose -f deploy/docker-compose.yml down
```

不要在需要保留数据时使用 `down -v`。

## Windows 一键脚本

已有 Docker 环境可以从仓库根目录运行：

```powershell
powershell -ExecutionPolicy Bypass -File scripts/start.ps1
powershell -ExecutionPolicy Bypass -File scripts/stop.ps1
```

不使用 Docker 时，执行根目录的 `install-native.cmd`、`start-native.cmd` 和 `stop-native.cmd`。本机运行数据全部位于 `.runtime`。

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

1. 修改默认账号密码、JWT 密钥和 MinIO 凭据。
2. 验证 `/health/ready` 返回 MongoDB、MinIO、Redis 全部正常。
3. 验证上传、预览、后台任务、回收站和导出。
4. 使用 `python scripts/compose-backup.py backup <仓库外目录>` 备份，并在新项目中演练恢复；命令见 `docs/operations.md`。
5. 记录版本、配置变化和回滚步骤。

升级、备份和数据治理要求见 `docs/operations.md` 与 `docs/migrations.md`。
