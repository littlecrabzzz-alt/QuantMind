# Tushare：持久化流水线隔离验收通过，准备云端发布

- 节点/任务：Mac，tushare-data-intake；状态：发布准备。
- 分支/worktree：codex/tushare-data-intake，/Users/lizeyu/.codex/worktrees/quantmind-tushare-data-intake；当前含 a985650，流水线尚待提交。
- 接续：20260908T154920Z-mac-pipeline-5d1b4b1b.md；更正注册入口为 backend/services/engine/qlib_app/celery_config.py，并非此前猜测的 backend/shared/celery_app.py。
- 本次文件：backend/shared/tushare_pipeline.py、tushare_store.py，engine/tasks/tushare_tasks.py，上述 Celery 配置，scripts/tushare_pipeline.py、tushare_mirror.py、test_tushare_pipeline.py，deploy/compose.cloud.yml 的 beat 角色，config/tushare-pipeline.example.json，docs/tushare-intake-runbook.md。无持续研究主题写入重叠。

已完成持久化队列/修订重查、Parquet、固定版本去重读取、带校验的 Mac 镜像和可安装的 15 分钟同步。7 项流水线测试及 5 项原始留存测试通过，Ruff 通过。测试仅临时目录和合成响应，无生产 token/数据库写入。

下一步：明确路径提交、合并 master、源代码同步及 handoff 元数据对齐；云端当前港股日常同步任务尚活跃，等空闲窗口发布 worker/beat，执行真实分页和两轮检查点续跑，镜像到 Mac 并在禁止网络条件下读取。全量历史、其他目录及 PIT 门禁仍未完成，不修改 RRG 状态。
