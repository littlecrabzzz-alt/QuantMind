# QuantDB PG 内存故障修复开始
- 节点 Mac；基线 e23b6712；双端 handoff passed；用户已要求修复并恢复同步。
- 候选 worktree：`/Users/lizeyu/.codex/worktrees/quantmind-quantdb-pg-memory-20260926`；分支 `codex/quantdb-pg-memory-20260926`。
- 分工：本任务修改 `backend/scripts/quantdb_daily_sync.py` 及其针对性测试；复用 Qlib 的受限 DuckDB 和逐标的流式读取能力，不修改 Binance 任务正在负责的 Qlib/RD 文件。
- 接续：`20260926T025441Z-mac-sync-recheck-e23b.md`。现有 PG 全市场 160 日 fetchdf 在 1.5 GiB worker 被 OOM 杀死。
- 最小修复：只扫描所需分区，逐标的计算同口径指标，限额 SQL/批量事务写入并及时释放资源；复用现有 Qlib 完整校验和原子发布。
- 验证：隔离样本数值/幂等/失败回滚检查，以及只读真实输入的受限容器运行。验证后协调云端相关服务窗口，保留恢复证据，只补派生 PG/Qlib；不覆盖研究固定输入或从 Mac 回灌。
