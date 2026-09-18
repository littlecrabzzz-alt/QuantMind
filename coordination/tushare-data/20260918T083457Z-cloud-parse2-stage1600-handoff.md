# Tushare：双路解析与 1600 阶段双端交接
- 时间、节点、任务标识：2026-09-18，Mac/Cloud，parse2-stage1600-handoff
- 状态：完成
- 接续：`20260918T083102Z-mac-document-parse2-stage1600-production.md`

Mac `master`、GitHub 与云端工作树已对齐到 `e45dcafffae604a39ebb89efef297a0d2ae8fc30`。云端一次 GitHub HTTPS fetch 长时间无进展，已仅终止该只读 fetch；工作树 HEAD 已由 handoff 的已验证 Git bundle 快进，因此使用 `git update-ref` 原子对齐云端 `origin/master`，未修改工作文件或数据。

云端 `dual_node_check --node cloud` 通过：sync idle、drift 空、errors 0、peer completion 100%。`ARCHIVE_RELOCATED.json` 存在，无全量 archive/acquisition unit 或进程；`tushare-research-cache.timer` 保持 active/enabled。Mac 全量归档 worker 继续运行。
