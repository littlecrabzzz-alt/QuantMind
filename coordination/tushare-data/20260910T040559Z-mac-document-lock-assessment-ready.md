# Tushare documents.sqlite 锁冲突评估就绪：不改运行码

- 时间、节点、任务标识：2026-09-10 04:05:59Z，mac，document-lock-assessment
- 状态：待交接；未合入 master、未部署生产
- 分支、worktree、测试/证据提交：`codex/tushare-document-lock-20260910`，`/Users/lizeyu/Documents/ChatGPT/投资/.worktrees/quantmind-tushare-document-lock`，`82c6971b05de7165e8b1457b7a83f560222e8a6a`
- 接续：`20260910T040227Z-mac-document-lock-assessment-start.md`、`20260910T035500Z-mac-realtime-doc-rrg-production-root.md`。

结论：当前生产证据不支持修改 journal mode、追加第二层重试或把锁失败降级为成功状态。`sqlite3.connect(timeout=10)` 已产生 `busy_timeout=10000ms`；生产无审计读锁的五批文档任务连续成功，已观察的两次失败均与验收脚本的显式只读事务重叠。在 DELETE journal 下，读事务不阻止 `BEGIN IMMEDIATE`，而是阻止写事务 commit；因此这类失败的 `*_db_wait_seconds` 很小，`*_db_total_seconds` 接近 busy timeout。

自然碰撞仍可能发生：文档登记和发布中的 `document_index` 都是 writer，与 document worker 的 claim/finish 共享 SQLite 单写者；这类碰撞会直接体现为 `*_db_wait_seconds`。全局 document consumer lock 使文档 worker 自身不会互相竞争。现有 10 秒等待已覆盖短登记/普通 noop index；如 writer 超过该界限，任务失败会可观察，事务完整回滚，下一调度周期可恢复。

百万行基准：Python 3.10.19 / SQLite 3.50.4，1,000,000 pending 行，319,303,680 bytes。为缩短测试用 200ms timeout（生产默认为 10,000ms）：50ms 审计读后 claim 在 67.5ms 成功；50ms writer 冲突后 claim 在 75.8ms 成功，其中 BEGIN 等待 73.4ms；超时审计读和 writer 均报 `OperationalError: database is locked`，部分 claim 为 0，锁释放后 1–2ms 内成功。finish 在超时读锁下的 document 仍为 pending/0 tries、0 attempts、原 claim 仍在；锁释放后相同结果原子写为 downloaded/1 try、1 attempt、claim 清除。WAL 对照在长读事务下 0.48ms 成功，但同时创建 `-wal/-shm`并引入 checkpoint/长读导致 WAL 增长、备份与回退合同；仅为修正外部长审计读锁不足以承担该运维变更。

为何不加重试/降级：SQLite busy handler 已是一层有界重试；再等 10 秒可使 90 秒 worker 超过 105 秒 soft limit。claim 超时可安全重调度，finish 超时则意味本轮内存中处理结果尚未入库；把后者改成绿色降级会隐藏真实未提交。raw 对象在 finish 前已以内容寻址原子保存，失败不删证据；任务失败和后续恢复应继续显式呈现。

验证：新增 4 项锁回归，文档定向共 68 项在 Python 3.10 通过；Ruff 和 `git diff --check` 通过。基准证据 `20260910T040559Z-mac-document-lock-assessment.evidence.json`，SHA256 `4a09d809a0904d929b667c86f65858d04e5f66fd8569d89037344a46bb7c22d6`；重放脚本 `/tmp/quantmind_document_lock_benchmark.py`，SHA256 `b58889662d169fbf3bd43c92a341ac9fe8ff6896c6884fdaf8e0207c38ee2a67`。上游请求、凭据读取、生产读写/锁、服务重启均为 0。

生产验收步骤：本候选只有测试/证据，合入后不需要重启服务。后续审计优先对 `sqlite3.Connection.backup` 生成的一致副本运行；必须读 live DB 时使用 autocommit 独立短查询、每条语句后立即释放，需要跨查询原子视图时先排空 Tushare acquisition 和 document worker。不人为在生产持锁验证；只读观察无审计重叠的至少 5 批自动任务，核对 `database is locked=0`、成功数、claim/finish `*_db_wait_seconds`、`*_db_total_seconds` 与当期 `document_index` 时间。只有在无审计读事务时仍重复超过 10 秒的自然 writer 冲突，才重新评估发布/登记排空时序，然后再做 WAL+在线 backup+checkpoint+回退的隔离演练。
