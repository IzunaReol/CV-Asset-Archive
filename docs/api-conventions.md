# API 约定

## 基础规则

接口统一使用 `/api/v1` 前缀和 JSON。时间字段使用带时区的 ISO 8601，列表接口使用 `page`、`page_size`、`sort`、`direction`、`q` 及领域筛选参数。

列表响应包含 `items`、`page`、`page_size` 和 `total`。批量操作返回 `succeeded` 与 `failed`，失败项包含 ID、错误码和原因；单项失败不回滚已成功项。

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

- 认证：`POST /auth/login`、`/auth/refresh`、`/auth/logout`
- 素材：`GET /assets`、`/assets/stats`、`/assets/{id}`
- 上传：`POST /assets/upload-sessions`、`/assets/upload-sessions/complete`
- 素材编辑：`PATCH /assets/{id}/remark`、`POST /assets/batch-tags`
- 标注：`GET /assets/{id}/annotation-overlays`
- 回收站：`POST /assets/batch-delete`、`GET /assets/trash/items`、`POST /assets/trash/restore`、`POST /assets/trash/empty`
- 关系：`GET|POST /relations`、`POST /relations/batch`、`POST /relations/preview`
- 自动关联：`POST /relations/annotation-match-preview`
- 关系详情：`GET /relations/{id}`、`POST /relations/{id}/revoke`、`GET /relations/graph/{asset_id}`
- 数据集：`GET|POST /datasets`、`GET|POST|DELETE /datasets/{id}/members`、`POST /datasets/{id}/members/preview`、`POST /datasets/{id}/versions`、`GET /datasets/{id}/compare`、`POST /datasets/{id}/restore`、`GET|POST /datasets/{id}/models`、`POST /datasets/{id}/export`
- 集合与视图：`GET|POST /collections`、`POST /collections/{id}/freeze`、`GET|POST /saved-views`
- 下载：`POST /exports`、`GET /jobs`、`GET /jobs/{id}`、`POST /jobs/{id}/retry`、`GET /exports/{id}/download-url`
- 管理：`/tag-definitions`、`/format-definitions`、`/users`、`/roles`、`/audit-logs`

CVAT 在线任务和 MLflow 接口尚未实现。

## 筛选

素材列表支持名称与备注模糊搜索、素材类型、无标签和高级条件。高级条件覆盖标签、备注、创建时间和修改时间，可选择全部条件或任一条件。分页默认 50，可选 20、50、100、200；前端“全部”会分批读取。

关系历史支持名称或备注、关系类型、状态、创建人和创建时间范围。

## 写入约束

- 单文件默认上限为 10 GB，通过 `MAX_UPLOAD_SIZE_BYTES` 修改。
- 关系源和目标不能相同；前端不允许选择自身，后端仍执行最终校验。
- 重复有效关系保持幂等，不创建第二条相同有效记录。
- 数据集不接受模型或手动添加的标注成员；图片的有效标注由当前数据集自动维护，已发布版本不随之改变。
- 新建模型关系仅允许“模型 → 已发布数据集版本”。图谱按版本成员推导素材路径，拒绝模型直连素材的写入。
- 撤销原因可不填且不限制业务字数；已撤销记录仍可在历史中查询。
- 清空回收站返回 `202` 和任务记录，实际文件清理由 Worker 执行。

## 常用状态码

- `400`：业务参数错误
- `401`：未认证或令牌失效
- `403`：权限不足
- `404`：资源不存在或已删除
- `409`：重复资源、状态冲突或正在使用
- `413`：文件超过上传限制
- `422`：请求校验或标注解析失败
- `503`：存储、队列或外部依赖不可用
