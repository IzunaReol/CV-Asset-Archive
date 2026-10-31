# 部署说明

## 使用条件

- Windows：Docker Desktop 和 Docker Compose v2。
- Linux：Docker Engine、Docker Compose v2、Bash、curl、`od`、`ss`（iproute2）。
- 默认占用 Web `8080`、API `8000`、MinIO `9000/9001` 端口。

## Windows 一键部署与启动

首次部署时双击仓库根目录的 `deploy-windows.cmd`，或在终端运行：

```powershell
.\deploy-windows.cmd
```

脚本会检查 Docker，必要时启动 Docker Desktop；首次创建 `.env` 时自动生成 JWT、管理员密码和 MinIO 凭据，然后构建镜像、启动服务并完成健康检查。已有 `.env` 时保留有效配置，仅替换缺失或明显不安全的默认凭据。
日常启动检测到 MongoDB 健康检查异常时，会保留现有数据卷并自动重新创建 MongoDB 容器，然后继续启动其他服务。

部署完成后的日常启动不重新构建镜像：

```powershell
.\start-windows.cmd
```

需要重新构建时再次运行 `deploy-windows.cmd`。

API 镜像的 Python 依赖在独立层安装：首次采用新 Dockerfile 构建仍需下载依赖；之后仅修改 `backend/app` 时会复用该层。修改 `backend/pyproject.toml` 或基础镜像时会重新安装依赖。

停止服务：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\stop.ps1
```

## Linux 一键部署与启动

### 方式一：服务器现场构建

首次部署：

```bash
bash deploy-linux.sh
```

脚本会检查 Docker Engine、Docker Compose v2、curl、磁盘空间、配置及首次部署端口；首次创建 `.env` 时自动生成 JWT、管理员密码和 MinIO 凭据，并把配置权限设为仅当前用户可读写。已有 `.env` 时保留有效配置，仅替换缺失或明显不安全的默认凭据。现场构建需要服务器能访问基础镜像和依赖源。

### 方式二：预构建镜像包

在与服务器相同 CPU 架构的 Linux 容器引擎上，从 **v2.1.0 同一份代码**制作镜像包：

```bash
bash scripts/package-linux-images.sh
```

脚本构建 API、Worker、前端，拉取 MongoDB、MinIO、Redis 镜像，默认在仓库的上一级目录输出 `cv-archive-v2.1.0-linux-images.tar`、`.sha256` 和 `.platform` 三个文件；可传入目标 tar 路径更改位置。把这三个文件和同一份项目代码复制到服务器；镜像包不要放入 Git。服务器首次部署：

```bash
bash deploy-linux.sh --bundle /path/to/cv-archive-v2.1.0-linux-images.tar
```

部署前会核对校验值、镜像架构、镜像名称、全部本地镜像、配置、磁盘与端口。制作镜像包与服务器上的 `APP_IMAGE_TAG`、`DOCKER_REGISTRY_PREFIX`、`MINIO_IMAGE` 必须一致。镜像模式使用 `--no-build --pull never` 启动，不在服务器现场构建或拉取。部署成功后检查六个容器、API 就绪、前端页面和 API 版本；任何检查失败都会退出并显示失败位置。请按服务器的实际域名和端口设置 `.env` 中的 `APP_BASE_URL`、`API_BASE_URL`、`MINIO_PUBLIC_ENDPOINT` 和端口。

日常启动检测到 MongoDB 健康检查异常时，会保留现有数据卷并自动重新创建 MongoDB 容器。

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

- Web：`http://localhost:8080`（可通过 `.env` 中的 `FRONTEND_PORT` 调整）
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

### v2.1.0 升级准备

从 v2.0.0 升级前，先备份 MongoDB、MinIO 与独立保存的部署配置，保留旧镜像。确认部署后，在仓库根目录执行：

```powershell
docker compose --env-file .env -f deploy/docker-compose.yml build api worker frontend
docker compose --env-file .env -f deploy/docker-compose.yml up -d --no-deps --no-build --pull never api worker frontend
```

以上启动命令仅使用已构建的本地应用镜像，要求基础服务已运行；缺失镜像时应明确报错，不临时拉取。版本号修改位于 `pyproject.toml`，因此此次构建可能使 Python 依赖层失效，不能承诺首次升级不安装依赖。备份结束后的服务恢复使用 `compose start`，只启动先前停止的容器；恢复到全新 Compose 项目的脚本仍使用 `up`，不能视为严格离线恢复。

验证服务健康、发布预检、图片分类与版本恢复、分类导出及模型参数并发保存。旧图片成员默认未划分，旧的一对多标注关系保留；部分导出可能因共享标注被拒绝。回滚镜像不会撤销数据更改，数据恢复须使用对应备份。版本范围及未完成验收见 [v2.1.0 发布说明](../docs/releases/v2.1.0.md)。

### 通用检查

1. 验证 `/health/ready` 返回 MongoDB、MinIO、Redis 全部正常。
2. 验证登录、上传、预览、后台任务、回收站和导出。
3. 使用 `python scripts/compose-backup.py backup <仓库外目录>` 备份，并在独立环境演练恢复。
4. 记录版本、配置变化和回滚步骤。

升级、备份和数据治理要求见 `docs/operations.md` 与 `docs/migrations.md`。
