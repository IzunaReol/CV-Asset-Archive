# API 服务

当前包及 OpenAPI 版本为 **2.1.0**，接口仍使用 `/api/v1`。本版增加数据集发布预检、图片分类与导出、模型搜索分页及参数修订号校验。详见[API 约定](../docs/api-conventions.md)、[数据集说明](../docs/datasets.md)和[模型参数](../docs/model-parameters.md)。

FastAPI 服务提供认证与 RBAC、素材元数据、分片上传会话、标签与格式、关系、模型图谱、数据集与保存视图、回收站、统一任务、用户和审计接口。刷新令牌使用 `HttpOnly` Cookie，服务启动时会恢复长时间无更新的异常任务、保护默认标签，并在生产模式拒绝默认密钥。

## 本地开发

从仓库根目录执行：

```powershell
python -m pip install -e "backend[dev]" -e worker
python -m uvicorn backend.app.main:app --reload --port 8000
```

服务依赖 MongoDB、MinIO 和 Redis。配置读取仓库根目录 `.env` 或环境变量，完整示例见 `/.env.example`。

## 验证

```powershell
python -m ruff check backend worker scripts
python -m pytest backend/tests -q
```

OpenAPI 页面为 `http://localhost:8000/docs`，存活和就绪检查分别为 `/health/live` 与 `/health/ready`。MongoDB 只保存元数据和对象键，大文件始终写入 MinIO。
