# 贡献指南

## 开发流程

1. 从 `main` 创建短生命周期分支，建议使用 `feat/`、`fix/`、`docs/` 或 `chore/`。
2. 提交信息遵循 Conventional Commits，例如 `feat(relations): prevent self association`。
3. 一个合并请求只处理一个清晰主题，并说明行为变化、验证结果和必要的界面截图。
4. 修改领域结构时增加可重复执行的 MongoDB 迁移。
5. 合并前通过后端检查、测试、前端构建和密钥扫描。

## 本地检查

```powershell
.\.runtime\venv\Scripts\python.exe -m ruff check backend worker
.\.runtime\venv\Scripts\python.exe -m pytest backend/tests -q
cd frontend
npm ci
npm run build
```

关系、上传、删除、权限和异步任务等关键行为应覆盖正常流程、非法输入、无权限和依赖失败。低影响样式调整无需编写重复实现的测试，但必须构建并实际检查白天和夜间模式。

## 数据规则

测试与演示只使用合成数据。不得提交：

- 真实图片、视频、标注和模型权重；
- MongoDB、MinIO、Redis 数据或导出包；
- 密码、令牌、预签名地址和内部服务地址；
- `plan.md`、原始 Word 实施方案或其他内部规划材料；
- `.runtime`、日志、缓存和临时测试目录。

## 文案与界面

用户可见文本使用简体中文。页面只保留一个主标题，功能说明保持简洁。成功消息可以使用“✓”，错误消息不得使用成功勾号。

## 远程操作

远程推送、创建合并请求和发布版本必须等待项目所有者完成手工测试并明确授权。本地实现、测试通过和本地提交不构成授权。
