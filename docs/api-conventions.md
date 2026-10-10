# API 约定

## 基础规则

接口统一使用 `/api/v1` 前缀和 JSON。时间字段使用带时区的 ISO 8601，列表接口使用 `page`、`page_size`、`sort`、`direction`、`q` 及领域筛选参数。

列表响应包含 `items`、`page`、`page_size` 和 `total`。素材列表还返回 `next_cursor`；按相同筛选和排序传入 `after=<next_cursor>` 可连续读取下一页，原有页码参数仍可使用。批量操作返回成功数、失败数和逐项 `details`；单项失败不回滚已成功项，明细达到保护上限时返回 `details_truncated=true`。

错误响应：

```json
{
  "error": {
    "code": "ASSET_NOT_FOUND",
    "message": "素材不存在或已删除",
    "request_id": "019...",
    "details": {}
  }
}
```

前端将成功与错误提示分开显示。错误提示不使用成功勾号；连接失败统一提示“无法连接至服务器，请重启后端服务”。

## 当前接口

- 认证：`POST /auth/login`、`/auth/refresh`、`/auth/logout`。刷新令牌仅通过 `HttpOnly` Cookie 传递，接口响应不返回刷新令牌；“保持登录”关闭时 Cookie 仅在当前浏览器会话有效。登录失败默认按 IP 和用户名组合限制为 5 分钟 5 次，超限返回 `429`。
- 素材：`GET /assets`、`/assets/stats`、`/assets/{id}`
- 上传：先使用 `POST /assets/upload-conflicts` 检查同名同类型文件，再通过 `POST /assets/upload-sessions` 创建上传会话；冲突处理支持 `overwrite` 和 `rename`，未明确选择时拒绝同名上传。`GET /assets/upload-sessions` 列出当前用户可恢复的大文件分片会话，`GET|DELETE /assets/upload-sessions/{id}` 用于恢复或取消，`POST /assets/upload-sessions/complete` 完成入库；64 MB 及以上文件使用 64 MB 分片。前端暂停时中止当前请求但保留会话，继续或重新选择同一文件时查询会话并跳过已完成分片。多文件可使用 `/assets/upload-sessions/batch` 和 `/assets/upload-sessions/complete-batch`，接口不限制文件总数；前端每 25 项提交一次，后端每 12 项作为一个执行窗口。生成上传地址失败时不会留下上传会话。
- 选择集：`POST /assets/selection-sets` 固化当前筛选结果，有效期 2 小时，最多 10 万项。批量标签、删除、集合及导出可以提交 `selection_id` 和 `excluded_ids`。
- 素材编辑：`PATCH /assets/{id}/remark`、`POST /assets/batch-tags`
- 标注：`GET /assets/{id}/annotation-overlays`
- 回收站：`POST /assets/batch-delete`、`GET /assets/trash/items`、`POST /assets/trash/restore`、`POST /assets/trash/empty`
- 关系：`GET|POST /relations`、`POST /relations/batch`、`POST /relations/preview`
- 自动关联：`POST /relations/annotation-match-preview`
- 关系详情：`GET /relations/{id}`、`GET /relations/{id}/revoke-preview`、`POST /relations/{id}/revoke`、`GET /relations/graph/{asset_id}`
- 数据集：`GET|POST /datasets`、`GET /datasets/options`、`GET /datasets/{id}`、`GET|POST|DELETE /datasets/{id}/members`、`POST /datasets/{id}/members/preview`、`POST /datasets/{id}/members/status`、`GET /datasets/{id}/tag-distribution`、`POST /datasets/{id}/versions`、`GET /datasets/{id}/versions/{version_id}`、`GET /datasets/{id}/compare`、`POST /datasets/{id}/restore`、`GET|POST /datasets/{id}/models`、`POST /datasets/{id}/export`
- 集合与视图：`GET|POST /collections`、`POST /collections/{id}/freeze`、`GET|POST /saved-views`
- 任务与下载：`POST /exports`、`GET /jobs`、`GET /jobs/{id}`、`GET /jobs/maintenance/export-size-backfill`、`POST /jobs/{id}/retry`、`POST /jobs/{id}/cancel`、`GET /exports/{id}/download-url`

数据集版本详情 `GET /datasets/{id}/versions/{version_id}` 使用 `page` 和 `page_size` 分页返回成员。版本对比统计覆盖全部成员；为控制响应体积，变更明细最多返回 1000 项，并通过 `truncated` 标记是否截断。
- 管理：`/tag-definitions`、`/format-definitions`、`/users`、`/roles`、`/audit-logs`

CVAT 在线任务和 MLflow 接口尚未实现。

## 筛选

素材列表支持名称与备注模糊搜索、素材类型、无标签和高级条件。高级条件覆盖标签、备注、创建时间和修改时间，可选择全部条件或任一条件。分页默认 50，可选 20、50、100、200；“全部”先加载 200 项，用户可以继续加载，批量操作使用服务端选择集。

关系历史支持名称或备注、关系类型、状态、创建人和创建时间范围。

## 写入约束

- 单文件默认上限为 10 GB，通过 `MAX_UPLOAD_SIZE_BYTES` 修改。
- 上传、标签和关系等普通写入允许管理员、数据管理员、标注员和算法工程师操作；删除素材、还原或清空回收站、删除数据集及覆盖同名原文件仅允许管理员和数据管理员操作。
- 上传完成处理任务使用上传会话内的固定任务 ID。任务持久化成功后才完成会话；未记录投递时间的等待任务会自动补发，Worker 对重复投递执行状态抢占。
- `POST /exports` 只接受 `asset_ids` 或 `selection_id`，不接受数据库查询对象。
- 关系源和目标不能相同；前端不允许选择自身，后端仍执行最终校验。
- 重复有效关系保持幂等，不创建第二条相同有效记录。
- 数据集不接受模型或手动添加的标注成员；图片的有效标注由当前数据集自动维护，已发布版本不随之改变。
- 新建模型关系仅允许“模型 → 已发布数据集版本”。图谱按版本成员推导素材路径，拒绝模型直连素材的写入。
- 撤销原因可不填且不限制业务字数；已撤销记录仍可在历史中查询。
- 清空回收站返回 `202` 和任务记录，实际文件清理由 Worker 执行。
- 默认标签带有 `built_in=true`，允许修改但拒绝删除；用户创建的未使用标签可以删除。

## 常用状态码

- `400`：业务参数错误
- `401`：未认证或令牌失效
- `403`：权限不足

### 权限校验

- 读取接口按菜单权限校验，例如素材库、数据集、关联关系、任务中心、回收站、标签、格式和用户管理。
- 写入接口按操作权限校验，菜单可见不代表允许修改。
- 自定义角色的 `menu_permissions` 和 `action_permissions` 由用户管理接口保存；操作权限必须属于已启用菜单。
- `GET /roles` 返回 `menus`、`actions`、固定角色默认权限和可复制的权限模板，供用户管理界面展示。
- `GET /permissions/me` 返回当前登录用户实时生效的角色、菜单和操作权限，前端用它处理权限变化和“我的权限”展示。
- 数据集写入拆分为创建编辑、成员管理、版本发布、版本恢复、删除和模型关联权限；保存视图使用独立操作权限。
- 创建素材导出必须同时具备任务中心、素材库和导出权限；创建数据集导出必须同时具备任务中心、数据集和导出权限。
- 管理员更新用户资料或权限后，服务端立即撤销该用户的刷新会话。
- `GET /audit-logs` 使用独立的系统日志菜单权限，支持 `q`、`actor_id`、`action`、`object_type`、`created_from`、`created_to`、`page` 和 `page_size`；`GET /audit-logs/export` 按相同条件导出 CSV，最多 10000 条。
- `GET /system/health` 返回 MongoDB、MinIO 和 Redis 的当前状态，供前端展示降级提示和恢复检测。
- `GET /system/overview` 按当前账号菜单权限返回概览统计，并包含各素材类型的数量和占用空间；`GET /system/search?q=` 搜索当前账号有权访问的素材、模型、数据集、关联关系、任务、用户、角色和系统日志。
- `POST|PUT|DELETE /role-templates` 管理团队可复用角色；`PUT|DELETE /role-definitions/{role}` 管理系统预设角色。管理员角色受保护，其他角色删除前会检查绑定用户并返回具体用户名。
- `POST /role-impact/{role}` 在保存角色权限前返回受影响用户及新增、移除的菜单和操作权限。
- 无权限请求统一返回 `403 / PERMISSION_DENIED`，不会以空列表掩盖越权访问。
- `404`：资源不存在或已删除
- `409`：重复资源、状态冲突或正在使用
- `413`：文件超过上传限制
- `422`：请求校验或标注解析失败
- `429`：登录失败次数超过短时限制
- `503`：存储、队列或外部依赖不可用
