# 计算机视觉素材归档管理系统

面向计算机视觉团队的素材归档与关系管理平台。系统统一管理图片、视频、标注、模型和压缩文件，并提供标签检索、标注预览、关系追溯、回收站和异步下载。

FiftyOne 是本项目的产品与交互参考，不是运行时依赖或数据真源。

## 当前进度

UI 方案 A“数据透镜”已通过评审，MVP 主流程已经可以本地测试：

- 登录、刷新令牌、五类角色和用户管理；
- 多文件预签名上传、格式自动识别、10 GB 默认单文件限制；
- 图片缩略图、视频封面和在线播放、原分辨率查看；
- 名称与备注模糊搜索、组合筛选、保存视图和多值标签；
- YOLO Detection、Pascal VOC、CVAT for images、COCO 图片标注包导入；
- 矩形框和多边形叠加预览；
- 图片与标注自动关联、模型与素材批量关联、关系历史和模型溯源；
- 软删除、回收站还原和后台彻底清理；
- 后台 ZIP 导出和限时下载；
- 标签、格式、用户、角色和审计数据管理。

CVAT 在线任务同步、MLflow 同步、10 万条数据性能基线、备份恢复演练和生产安全加固仍在后续阶段。

## 技术架构

- 前端：Vue 3、TypeScript、Vite
- API：Python 3.12、FastAPI、Pydantic、PyMongo Async
- 元数据：MongoDB
- 对象存储：MinIO
- 异步任务：Celery、Redis
- 媒体处理：Pillow、FFmpeg
- 部署：Windows 本机运行环境或 Linux Docker Compose

详细设计见 [系统设计](docs/system-design.md)、[API 约定](docs/api-conventions.md)、[关联撤销设计](docs/relation-revoke.md) 和 [运维说明](docs/operations.md)。

## Windows 本机运行

要求 Windows 11、Python 3.12+、Node.js 20+ 和 curl。所有依赖、数据和日志均保存到项目目录的 `.runtime`，不会创建 Windows 服务。

首次安装：

```powershell
.\install-native.cmd
```

下载直连失败时，安装脚本会尝试 `http://127.0.0.1:7890`。也可以指定其他代理：

```powershell
powershell -ExecutionPolicy Bypass -File scripts/install-native.ps1 -FallbackProxy http://127.0.0.1:7890
```

启动和停止：

```powershell
.\start-native.cmd
.\stop-native.cmd
```

启动后访问 `http://localhost:5173`，初始账号和密码均为 `admin`。日志位于 `.runtime/logs`，数据位于 `.runtime/data`。

## Docker Compose 部署

服务器建议使用 Linux 和 Docker Compose。复制配置并更换所有占位凭据：

```bash
cp .env.example .env
docker compose -f deploy/docker-compose.yml up --build -d
```

访问地址：

- Web：`http://localhost:8080`
- API 文档：`http://localhost:8000/docs`
- 就绪检查：`http://localhost:8000/health/ready`
- MinIO 控制台：`http://localhost:9001`

PowerShell 一键启动、停止和离线镜像导入导出见 [部署说明](deploy/README.md)。

## 配置

常用配置在 [.env.example](.env.example) 中：

| 配置项 | 用途 | 默认示例 |
| --- | --- | --- |
| `JWT_SECRET` | 访问令牌签名密钥 | 必须替换 |
| `INITIAL_ADMIN_USERNAME` | 初始管理员 | `admin` |
| `INITIAL_ADMIN_PASSWORD` | 初始管理员密码 | `admin` |
| `MAX_UPLOAD_SIZE_BYTES` | 单文件上传上限 | `10737418240` |
| `EXPORT_EXPIRY_HOURS` | 导出下载有效期 | `72` |
| `MINIO_*` | 对象存储连接参数 | 仅示例 |
| `MONGODB_*` | MongoDB 连接参数 | 仅示例 |
| `REDIS_URL` | Celery 队列连接 | 仅示例 |

面向团队部署前必须修改默认管理员密码、MinIO 凭据和 JWT 密钥。

## 开发与验证

```powershell
.\.runtime\venv\Scripts\python.exe -m ruff check backend worker
.\.runtime\venv\Scripts\python.exe -m pytest backend/tests -q
cd frontend
npm ci
npm run build
```

隔离数据库的 API 流程测试使用 `scripts/runtime-e2e.py`。测试与验收范围见 [测试说明](docs/testing.md)，发布前逐项检查 [v0.1.0 发布检查单](docs/release-checklist.md)。

## 仓库规则

公开仓库不得包含真实业务素材、模型权重、数据库、运行日志、访问凭据或个人信息。`plan.md` 和原始 Word 实施方案只作为本地输入，不进入 Git 历史。

提交前阅读 [贡献指南](CONTRIBUTING.md)、[安全策略](SECURITY.md) 和 [项目治理](docs/project-governance.md)。本项目采用 [Apache License 2.0](LICENSE)。
