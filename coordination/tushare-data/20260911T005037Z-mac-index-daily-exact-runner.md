# Tushare index_daily exact runner candidate

- 时间、节点、任务标识：2026-09-11 00:50:37 UTC，Mac，`index_daily_exact_runner`
- 状态：完成，待主任务集成和云端生产执行
- 基线：`master` at `a90bd68dc3816e3ebd2ce03906727ffc711ef373`
- 分工：仅新增 `index_daily` exact prepare、runner、聚焦测试和本记录；未修改共享进度、注册表或其他任务文件。

实现固定当前 release、权威配置、全部 pristine 候选任务库存、选中任务和 prepare/runner 代码哈希。prepare 在共享读锁下只选择 `structured/history`、`pending`、`tries=0` 且无 attempt 的任务，按指数代码分轮取最新年度区间。执行必须经过 authority、schema 6、ENABLED、独占锁、100 GiB 空闲空间、Tushare Token 和已复核 500 rpm 门控；最多 360 次、90 秒，不发布也不切换 `CURRENT.json`。默认 plan-only 明确不访问 authority、凭据、网络或写入。

验证：`PYTHONPATH=scripts:. python3 -m unittest scripts.test_tushare_index_daily_batch scripts.test_tushare_rate_policy -v` 共 26 项通过；三个新增文件 `py_compile` 通过且无超过 88 字符的行。Mac 未安装 `ruff` 命令。未部署、未连接生产 authority、未调用 Tushare。
