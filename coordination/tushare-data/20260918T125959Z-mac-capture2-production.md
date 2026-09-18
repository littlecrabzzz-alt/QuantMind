# Mac Tushare 双路隔离采集生产验收

- 时间、节点、任务标识：2026-09-18，Mac，capture2
- 状态：生产保留 `acquisition_capture_workers=2`；Mac 仍为全量归档唯一写入者
- 代码：`master` / `origin/master` `0efe3923237a673438b8ca337d0285e3c82ad047`
- 接续：`20260918T124332Z-mac-capture2-start.md`

候选新增一个默认为 1、上限为 2 的 `acquisition_capture_workers`。两路只允许在 process 隔离和 pipeline depth 2 下启用；主进程仍在每次提交前逐个持久化共享账户/API gate，每日配额在 HTTP 前使用原有 SQLite 事务原子预留，结果、任务状态和分区仍只由主进程提交。崩溃后 `inflight` 恢复、已预留 gate 不回滚和内容寻址对象的原子创建不变。

验证通过 67 项 pipeline、rate-policy、archive-worker 和 installer 回归；新本地 HTTP 夹具确认峰值两路、两个 observation 均持久化，并拒绝非法 worker 值与 thread+2 组合。Ruff lint、Python 编译和 `git diff --check` 通过。同样 40 个本地 HTTP+落盘任务中，单路用时 8.385 秒，双路 5.212 秒，缩短约 37.8%，服务端峰值严格为 1/2。

部署原子移出 `ENABLED` 后等待在途周期提交，worker 于 2026-09-18T12:50:13Z 写出 `disabled`，再卸载 LaunchAgent、原子更新私有配置、按原 SHA 恢复 marker 并重新安装。数据库、原始对象和文档目录没有移动或重建。配置 SHA-256 由 `9c5783305de8e22065eefefd9f9ff575645bbd1fe37c7e14081a2dcc0662aca5` 变为 `b7d27d2aae6596d77fca7794be7bdf86f54b0bfbde9638dfb0c1e2a22dbf9c83`，`ENABLED` SHA-256 保持 `6b45163b577df25f4e6842501fc95128649c5b129daddf3958224864008eda40`，配置、marker 和 `archive.env` 权限均为 0600。

生产仍保持 `batch_requests=800`、`batch_seconds=100`、账户 500 次/分钟、depth 2/process 及全部接口级频控。部署前最近五个单路周期为 420/393/416/406/502 次，中位数 416。配置指纹触发一个 0 请求的正常 `planning_only` 周期后，三个双路周期分别完成 601/616/614 次真实请求，采集阶段为 102.795/100.295/100.248 秒，中位数 614，较单路中位数提高约 47.6%。三轮报告的 `http_workers=2`、高水位 2、gate reservation 与请求一一对应，`failed_stage` 均为空。

三轮精确 attempt 范围为 rowid 704661–706491，共 1,831 条：`sample_ok=977`、`empty_unverified=799`、`possibly_truncated=55`；`rate_limited`、`transport_error`、`api_error`、`invalid_response` 和 `permission_denied` 均为 0。私有无凭据回执为 `validation/capture-workers-gray-v1.843929384fdadc796086817898037801b2b0bced34bf19d8565bf5a9cbde0800.json`，文件 SHA-256 与名称一致，权限 0600。

三轮同时每轮处理 2,000 个文档阶段任务，并各登记 100 个附件观测。连续登记将更多历史附件显式加入队列，待下载数由部署前的 3,914,531 增到 4,227,249；这是历史发现快于当前下载吞吐，不是数据回滚。下一个提速对象是下载阶段，必须与本次结构化采集增益分开验收。

`com.quantmind.tushare-archive` 以 PID 9537 运行，自部署后未退出；磁盘约 3.6 TiB，已用 1.4 TiB，可用 2.1 TiB。全量同步仍未完成，Mac worker 继续常驻运行；云端只对齐代码并保留受限研究缓存，不恢复全量 writer。
