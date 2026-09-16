# CV Asset Archive

[English](README.en.md) | 简体中文

面向计算机视觉团队的素材归档与关系管理系统。用于集中保存图片、视频、标注文件、模型和压缩文件，并完成检索、标注预览、关系追溯、回收站管理和异步导出。

## 功能

- 图片、视频、标注、模型和压缩文件批量上传
- 文件格式自动识别，单文件限制默认 10 GB，可通过环境变量调整
- 图片缩略图、视频封面、在线播放和原分辨率预览
- 名称及备注模糊搜索、组合筛选、保存视图和多值标签
- YOLO Detection、Pascal VOC、CVAT for images、COCO 标注包导入
- 矩形框和多边形标注叠加预览
- 图片与标注自动关联、模型与素材批量关联、关系历史和模型溯源
- 素材软删除、回收站还原和后台物理清理
- 后台 ZIP 导出、任务进度和限时下载
- 用户、角色、标签、格式和审计数据管理
- 数据集成员管理、不可变版本、自定义版本号、版本对比及恢复
- 数据集复制、模型版本关联和数据集导出
- 白天模式与夜间模式

## 技术栈

| 模块 | 技术 |
| --- | --- |
| 前端 | Vue 3、TypeScript、Vite |
| API | Python 3.12、FastAPI、Pydantic、PyMongo Async |
| 元数据 | MongoDB |
| 对象存储 | MinIO |
| 异步任务 | Celery、Redis |
| 媒体处理 | Pillow、FFmpeg |
| 部署 | Windows 本机环境、Linux Docker Compose |

详细说明见[系统设计](docs/system-design.md)、[API 约定](docs/api-conventions.md)、[关联撤销](docs/relation-revoke.md)和[运维说明](docs/operations.md)。

## Windows 本机运行

运行环境：Windows 11、Python 3.12+、Node.js 20+、curl。依赖、数据和日志保存在项目目录的 `.runtime` 中，不创建 Windows 服务。

首次安装：

```powershell
.\install-native.cmd
```

下载失败时，安装脚本会尝试 `http://127.0.0.1:7890`。也可以指定代理：

```powershell
powershell -ExecutionPolicy Bypass -File scripts/install-native.ps1 -FallbackProxy http://127.0.0.1:7890
```

启动和停止：

```powershell
.\start-native.cmd
.\stop-native.cmd
```

启动后访问 `http://localhost:5173`。初始用户名和密码均为 `admin`。日志位于 `.runtime/logs`，数据位于 `.runtime/data`。

## Docker Compose 部署

服务器建议使用 Linux 和 Docker Compose。复制配置文件并更换所有默认凭据：

```bash
cp .env.example .env
docker compose -f deploy/docker-compose.yml up --build -d
```

默认地址：

- Web：`http://localhost:8080`
- API 文档：`http://localhost:8000/docs`
- 就绪检查：`http://localhost:8000/health/ready`
- MinIO 控制台：`http://localhost:9001`

PowerShell 启停脚本和离线镜像导入、导出方法见[部署说明](deploy/README.md)。

## 配置

常用配置位于 [.env.example](.env.example)：

| 配置项 | 用途 | 默认示例 |
| --- | --- | --- |
| `JWT_SECRET` | 访问令牌签名密钥 | 部署时必须替换 |
| `INITIAL_ADMIN_USERNAME` | 初始管理员 | `admin` |
| `INITIAL_ADMIN_PASSWORD` | 初始管理员密码 | `admin` |
| `MAX_UPLOAD_SIZE_BYTES` | 单文件上传上限 | `10737418240` |
| `EXPORT_EXPIRY_HOURS` | 导出文件有效期（小时） | `72` |
| `MINIO_*` | 对象存储连接参数 | 示例值 |
| `MONGODB_*` | MongoDB 连接参数 | 示例值 |
| `REDIS_URL` | Celery 队列连接地址 | 示例值 |

团队部署前必须修改默认管理员密码、MinIO 凭据和 JWT 密钥。

## 开发与测试

```powershell
.\.runtime\venv\Scripts\python.exe -m ruff check backend worker
.\.runtime\venv\Scripts\python.exe -m pytest backend/tests -q
cd frontend
npm ci
npm run build
```

隔离数据库的 API 流程测试使用 `scripts/runtime-e2e.py`。完整范围见[测试说明](docs/testing.md)和 [v1.1.0 发布检查单](docs/release-checklist.md)。

## v1.1.0 升级

升级前备份 MongoDB 和 MinIO，停止 API 与任务进程后更新代码。启动时自动执行集合到数据集的幂等迁移；素材对象文件不迁移。更新前端依赖并重新构建，详细操作见[数据集说明](docs/datasets.md)。回退 v1.0.0 前应恢复升级前数据库备份。

已知限制及后续工作见[发布说明](docs/releases/v1.1.0.md)。

## 项目文档

- [系统设计](docs/system-design.md)
- [API 约定](docs/api-conventions.md)
- [部署说明](deploy/README.md)
- [运维说明](docs/operations.md)
- [测试说明](docs/testing.md)
- [路线图](docs/roadmap.md)
- [贡献指南](CONTRIBUTING.md)
- [安全策略](SECURITY.md)

## 仓库规则

仓库不接收真实业务素材、模型权重、数据库、运行日志、访问凭据或个人信息。原始规划文件和内部实施方案不进入 Git 历史。具体要求见[项目治理](docs/project-governance.md)。

## 许可证

本项目采用 [Apache License 2.0](LICENSE)。
