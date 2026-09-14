# API 服务

FastAPI 服务提供认证与 RBAC、素材元数据、预签名上传、标签与格式、关系、模型图谱、集合与保存视图、回收站、导出任务、用户和审计接口。

## 本地开发

从仓库根目录执行：

```powershell
python -m pip install -e "backend[dev]" -e worker
python -m uvicorn backend.app.main:app --reload --port 8000
```

服务依赖 MongoDB、MinIO 和 Redis。配置读取仓库根目录 `.env` 或环境变量，完整示例见 `/.env.example`。

## 验证

```powershell
python -m ruff check backend worker
python -m pytest backend/tests -q
```

OpenAPI 页面为 `http://localhost:8000/docs`，存活和就绪检查分别为 `/health/live` 与 `/health/ready`。MongoDB 只保存元数据和对象键，大文件始终写入 MinIO。
