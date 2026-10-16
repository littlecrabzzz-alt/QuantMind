# 脚本使用入口

用途：在执行维护或研究脚本前确认作用域与副作用，不维护一份易过期的全量脚本目录。

- 应用部署与本地开发从[根 README](../README.md)进入；脚本不因位于本目录就代表被当前部署采用。
- `frontend/` 是前端安装、资产和构建辅助，调用方式以 `electron/package.json` 为准。
- `check_storage_readiness.py` 是已配置应用容器内的只读检查：数据库 `SELECT 1`、Redis 持久化状态、磁盘余量。用 `python -I -S /app/scripts/check_storage_readiness.py` 执行，不导入应用启动器。
- `storage_maintenance.py` 使用 `plan` / `apply` 两阶段：先生成清理计划，再审阅并按 CLI 要求确认；不能用磁盘紧张作为未经授权删除数据/备份的理由。
- `register_models_from_dir.py` 会给指定账号写模型注册记录，先用 `--dry-run` 查看，并显式指定 `--user-id`、必要时 `--tenant-id/--models-root`。文件存在不等于模型已注册或已通过质量门禁。
- 训练、回测、采集、同步和发布脚本可能联网、收费、写库或覆盖产物。先读脚本入口和参数，确认输入、输出、目标实例和只读选项；不要把默认路径或历史日期当作当前研究配置。

具体业务说明从[文档索引](../docs/README.md)查找。一次性实验结论不在本目录维护第二份报告，历史修改可查 Git。
