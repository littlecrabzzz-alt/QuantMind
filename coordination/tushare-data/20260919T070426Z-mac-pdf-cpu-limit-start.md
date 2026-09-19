# Mac Tushare 大 PDF CPU 限制修复开始

- 时间、节点、任务：2026-09-19T07:04:26Z，Mac 全量归档所有者，pdf-cpu-limit。
- 状态：候选已验证，待合入与生产切换。
- 分支、worktree、提交：`codex/tushare-pdf-cpu-limit`，`/Users/lizeyu/.codex/worktrees/QuantMind/tushare-pdf-cpu-limit`，候选 `226e64f0`。
- 分工：仅修改 `backend/shared/tushare_documents.py` 与 `scripts/test_tushare_documents.py`；不接管其他 agent 的研究和 RRG 文件。
- 接续：`20260918T054300Z-mac-pdf-parser-v4-production.md`。

生产只读抽检发现有效的 160、303、951 页 PDF 被固定 15 秒 CPU 限制以 `parser_process_failed` 误拒；不受该限制的同版解析分别约 19、19、30 秒并成功。候选把 CPU 上限提高到 90 秒，仍保留父进程墙钟、1 GiB 常驻内存、5000 页、8 MiB 文本和 32 MiB 输出限制，并把 SIGXCPU 正确归类为超时。

验证：文档专项 102 项通过，Ruff 和 diff check 通过；951 页、43,950,875 字节生产保留 PDF 经候选正式入口在约 28.8 秒解析 1,694,931 字节文本。原始文件与生产数据库未修改。
下一步：精确合入 master，等待当前采集轮自然完成后更新本地运行时，只重启 Tushare archive worker；验证真实失败样本恢复且主同步继续。
