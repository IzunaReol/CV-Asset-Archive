# 前端模块结构

前端采用 Vue 3 单文件组件。`App.vue` 负责应用外壳、登录会话、菜单导航和暂未迁移的跨页面弹窗；独立业务页放在 `frontend/src/views/`，可复用交互组件放在 `frontend/src/components/`，状态与异步流程放在 `frontend/src/composables/`，请求封装统一由 `frontend/src/api.ts` 提供。

## 当前边界

| 模块 | 页面或组件 | 状态与流程 |
| --- | --- | --- |
| 系统概览 | `views/OverviewView.vue` | 页面内加载、统计图计算及刷新 |
| 项目概览 | `views/ProjectOverviewView.vue` | 项目多选、聚合结果、空区域与详情导航 |
| 参数管理 | `views/ParametersView.vue` | 指标及分类维护、分类折叠、编辑确认 |
| 数据集与模型参数 | `DatasetView.vue`、`components/ModelParametersDialog.vue` | 数据集当前成员和版本管理；共享模型参数表单供素材详情与模型管理复用 |
| 任务中心 | `views/JobsView.vue` | `composables/useJobs.ts` 负责查询、筛选、分页、下载、重试和取消；外壳负责轮询调度及导航角标 |
| 回收站 | `views/TrashView.vue` | `composables/useTrash.ts` 负责列表、选择、分页、还原、清空及任务结果轮询；外壳只提供确认弹窗、通知和素材库刷新 |
| 系统日志 | `views/AuditLogsView.vue` | `composables/useAuditLogs.ts` 负责筛选、分页、详情和导出；`auditPresentation.ts` 负责日志文案格式化 |
| 标签和格式管理 | `views/TagsView.vue`、`views/FormatsView.vue` | 页面只负责展示与派发操作，数据与编辑弹窗暂由外壳维护，因为标签和格式也用于素材库及上传 |
| 全局搜索与确认 | `components/GlobalSearch.vue`、`components/ConfirmationDialog.vue`、`components/PermissionImpactDialog.vue` | 搜索组件自行管理搜索状态；确认流程由 `composables/useConfirmation.ts` 管理 |
| 上传与模型溯源 | — | `uploadTransfer.ts` 管理批量/分片传输；`composables/useLineageGraph.ts` 管理图谱派生数据 |

组件不直接修改父级权限或导航状态：通过显式属性接收权限和数据，通过事件上报导航及管理操作。业务接口调用放在页面或对应逻辑模块，不放入纯展示组件。登出时必须清除仍由外壳持有的跨页面缓存。

## 后续拆分顺序

异步详情加载使用当前请求标识保护状态：切换素材或关闭详情后，旧详情、标注、历史及备注保存响应不得写入当前页面。历史展开按接口总数继续请求分页。跨页面进入数据集详情和返回列表必须显式重置导航状态；不能让列表入口复用遗留详情状态。

素材库、关联关系、模型溯源及部分共享弹窗仍集中在 `App.vue`。后续逐个迁移时，先界定独立状态与跨页面共享状态，再抽出页面及逻辑模块，并为登录、权限、筛选、弹窗和数据刷新补充回归用例。避免只把模板移动到新文件、却通过大量隐式共享状态继续耦合外壳。

验证命令见 [测试与验收](testing.md)。本轮页面重构的自动化用例使用模拟 API；隔离 API 测试仅覆盖后端全流程，不代替真实浏览器与生产数据验收。
