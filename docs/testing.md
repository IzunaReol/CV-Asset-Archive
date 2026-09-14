# 测试与验收

## 自动化检查

后端：

```powershell
.\.runtime\venv\Scripts\python.exe -m ruff check backend worker
.\.runtime\venv\Scripts\python.exe -m pytest backend/tests -q
```

前端：

```powershell
cd frontend
npm ci
npm run build
```

隔离 API 流程测试使用独立数据库，覆盖上传、自动关联、模型关系、幂等、图谱、撤销、冲突和类型校验：

```powershell
.\.runtime\venv\Scripts\python.exe scripts/runtime-e2e.py
```

运行前应将 API 指向独立的 `MONGODB_DATABASE`，测试结束脚本会清理该数据库与对应 MinIO 对象。

## 手工验收清单

1. 使用五类角色检查页面、接口和越权拒绝。
2. 上传图片、视频、标注、模型、普通压缩文件与“图片+标注”包。
3. 验证名称和备注模糊搜索、多条件筛选、多值标签、保存视图和分页。
4. 验证图片原图、标注框、视频播放、上一个与下一个媒体切换。
5. 验证 YOLO、VOC、CVAT Images、COCO 的导入、类别名称、矩形框和多边形。
6. 验证自动关联的成功、已有关系、重名冲突和未匹配分类。
7. 验证模型不能关联自身，重复提交不产生重复有效关系。
8. 验证关系历史、中文来源、可选撤销原因、图谱刷新和撤销详情。
9. 验证删除进入回收站、还原、后台清空状态和对象物理删除。
10. 验证 ZIP 仅包含所选文件、同名处理、任务重试和过期下载。
11. 验证白天与夜间模式、窄窗口、弹窗层级、错误提示和长文件名。
12. 重启全部服务，验证数据、任务状态和预览恢复。

## 发布门槛

- 自动化检查全部通过；
- 使用合成数据完成全流程手工验收；
- 在全新 Linux 主机复现 Docker Compose 部署；
- 完成 10 万条元数据常用查询 P95 小于 500 ms 的基线；
- 完成 MongoDB 与 MinIO 备份恢复演练；
- 依赖和镜像无高危漏洞，仓库无密钥、真实素材或运行数据；
- 项目所有者明确允许后才能推送 Git。

测试夹具必须使用合成数据，不得提交真实业务素材。
