# 运维与数据治理

## 数据位置

MongoDB 保存元数据、标签、关系、用户、任务和审计；MinIO 保存原文件、预览和导出包。Redis 只保存 Celery 队列与临时结果，不作为业务真源。

Windows 本机模式将组件、数据库、对象、日志和临时文件放在项目的 `.runtime`。Docker Compose 使用 `mongodb-data`、`minio-data` 和 `redis-data` 命名卷。

## 删除与回收站

素材删除先写入 `archived_at` 并从素材库隐藏。回收站可以还原素材。清空回收站只提交后台任务，前端不等待物理删除完成；Worker 删除原文件、预览、资产版本和相关关系，并写入审计日志。仍被有效资产共用的对象键不会重复删除。

物理清理不可恢复。执行前应确认备份、Worker 和 MinIO 可用，并在任务中心或任务接口检查结果。

## 导出

导出任务固化提交时的资产 ID，在后台生成 ZIP。压缩包根目录只包含所选原文件；同名文件自动增加序号，不包含 `assets` 目录和 `manifest.json`。下载地址默认 72 小时有效，可通过 `EXPORT_EXPIRY_HOURS` 调整。

## 备份与恢复

建议每日备份 MongoDB 和 MinIO，并保留至少 30 天。生产环境应为 MinIO 配置独立备份目标或复制策略。

Docker Compose 部署可使用 `python scripts/compose-backup.py backup <仓库外备份目录>` 备份 MongoDB 和 MinIO。脚本会暂时停止 API 和 Worker，生成文件校验清单，然后恢复原先运行的服务。备份目录可能包含真实素材和敏感数据，应单独加密、限制访问，不能提交到 Git。

恢复演练使用全新的 Compose 项目名，例如 `python scripts/compose-backup.py restore <备份目录> --project cv-archive-restore-test --confirm-new-project`。脚本先校验所有备份文件，再确认目标项目的 MongoDB、MinIO、Redis 卷均不存在；已有卷一律拒绝覆盖。恢复完成后检查服务健康状态并抽查素材、关系、版本、回收站和导出。此脚本尚未在全新 Linux 主机完成实机演练。

恢复顺序：

1. 停止 API 和 Worker；
2. 恢复 MongoDB；
3. 恢复 MinIO 对象；
4. 以空闲队列启动 Redis；
5. 启动 API 和 Worker并检查 `/health/ready`；
6. 抽查素材、预览、关系、回收站和导出。

`.env` 不进入业务备份包，凭据应由部署系统独立恢复。升级数据库结构前必须先完成备份，迁移规则见 [MongoDB 迁移规范](migrations.md)。

## 日志与审计

API 日志记录请求 ID、路径、状态和耗时；不得记录密码、令牌、预签名 URL 或文件正文。审计覆盖用户、标签、上传、素材修改、关系创建与撤销、回收站清理和导出。

## 任务状态

任务状态为 `queued → running → succeeded | failed | cancelled`。任务失败时保存错误码和可展示原因；权限不足和临时目录不可写必须及时结束任务。失败任务可以重新提交，原任务记录保留。导出任务支持主动取消，Worker 会在分文件处理节点停止并清理竞争情况下已经生成的压缩包；清空回收站涉及物理删除，不支持中途取消。

Worker 每 15 秒为运行中任务写入一次心跳。API 启动时会把超过 `JOB_STALE_MINUTES`（默认 120 分钟）且没有更新的运行中任务标记为 `TASK_INTERRUPTED`，素材处理任务会同步把素材转为失败状态，供管理员核对后重试。

数据集写操作使用带到期时间的租约，并在操作期间续租。进程异常退出后，租约过期可再次写入；若退出发生在版本恢复过程中，下一次写入会先完成上次恢复。恢复前仍应保存 MongoDB 与 MinIO 备份。

## Linux 权限

Linux 部署需要保证容器用户能写入 Worker 临时目录及挂载卷。若宿主机使用绑定目录，应预先设置目录所有者和读写权限。MinIO 对象访问依赖服务凭据，不依赖浏览器用户对宿主机目录的权限。
