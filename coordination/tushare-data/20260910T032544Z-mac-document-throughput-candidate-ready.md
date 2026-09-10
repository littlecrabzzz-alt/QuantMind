# Tushare 附件队列吞吐候选就绪

- 时间、节点、任务标识：2026-09-10 03:25:44Z，mac，document-throughput-candidate
- 状态：待交接；未合入 master、未部署生产
- 分支、worktree、代码提交：`codex/tushare-document-throughput-20260910`，`/Users/lizeyu/Documents/ChatGPT/投资/.worktrees/quantmind-tushare-document-throughput`，`0a96292f2158e38e2db1020faf659224736b851b`
- 接续：`20260910T031801Z-mac-document-throughput-candidate-start.md`；根据 `20260910T022030Z-mac-document-throughput-readonly-structured.md` 的只读审查实施。

实现：claim schema v1 在全局 consumer lock 内以单一 SQLite 事务迁移到 v2，新增仅覆盖 `download_status='pending'` 的 `document_pending_claim_order(id)` 部分索引。pending 按 `id` 有序取前 N，retry 仍使用原 `(download_status,retry_after)` 到期索引，然后与 parse 候选按 `id` 合并；保留原有全局锁、2 下载/1 解析、5 次重试、raw/result 证据和 100GiB 停采保护。worker 回执新增 setup/claim/finish 的 `BEGIN IMMEDIATE` 等锁时间、整体 DB 时间及 download/parse 单任务时间和调用数。迁移创建索引失败时，版本和索引同事务回滚。

代表性基准：Python 3.10.19 / SQLite 3.50.4，临时库 1,100,004 行（约 1,055,751 pending，其余为 parsed/blocked/parse/retry 尾部，另加明确边界行）。九次热查询中位数：download claim `0.0943865s -> 0.000037417s`（约 2522.6x），混合 claim `0.1219820s -> 0.000965959s`（约 126.3x）。初次索引事务 0.761984s，增加 78,712,832 bytes。新旧查询 top-N 完全一致；未到期 retry、未到期 pending 和有效 claim 未被重取，到期 retry 与 parse 可正常选中。证据 `20260910T032544Z-mac-document-throughput-candidate.evidence.json`，SHA256 `b448f794ff0b184608c72171da365bec509c9f8b6797a5026d69ea2d6cb27a4d`；本地可重放脚本 `/tmp/quantmind_document_claim_benchmark.py`，SHA256 `9176ebb6f89531666afb40a1d06bca564d18d19882fbf3ae3ae1df6f5fd6d432`。

验证：`uv run --no-project --python 3.10 --with httpx --with fastapi --with pyyaml --with reportlab --with pypdf python -m unittest discover -s scripts -p 'test_tushare_document*.py'` 通过 64 项；`uvx ruff check backend/shared/tushare_documents.py scripts/test_tushare_document_parallel.py` 和 `git diff --check` 通过。全部测试与基准只使用临时 SQLite，上游请求、Token/凭据读取、生产写入、服务重启均为 0。

局限：这证明了选队路径和语义，不是生产端到端文档吞吐保证；索引维护对登记写入的实际成本、云端 SQLite 版本和真实移动队列收益尚未验收。集成人合入前应复核差异；部署时先排空 document worker，仅重启该 worker，然后在首个真实回执中核对迁移时间、索引查询计划、timing 字段和短窗实际 parsed/hour；如首次迁移失败，v1 会保留供下次有界重试。
