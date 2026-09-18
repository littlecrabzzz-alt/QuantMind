# Tushare：文档重叠优化双端交接
- 时间、节点、任务标识：2026-09-18，Mac/Cloud，document-overlap-handoff
- 状态：完成
- 接续：`20260918T080050Z-mac-document-overlap-production.md`

`master` 与云端工作树已对齐到 `d7be224713223816e56e7515684be0a9fb91219f`，云端随后显式 fetch 使 `origin/master` 同步。云端 `dual_node_check --node cloud` 通过：同步 idle、drift 空、errors 0、peer completion 100%。`ARCHIVE_RELOCATED.json` 存在，没有全量 archive/acquisition unit 或进程；`tushare-research-cache.timer` 保持 active/enabled。Mac 的完整归档 worker 继续真实采集，云端拓扑未变。
