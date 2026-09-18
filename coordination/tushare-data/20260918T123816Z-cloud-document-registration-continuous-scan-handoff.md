# Tushare 文档登记连续扫描云端交接

- 时间、节点、任务标识：2026-09-18，cloud，document-registration-continuous-scan
- 状态：代码和验收记录已对齐；云端角色不变
- 接续：`20260918T123633Z-mac-document-registration-continuous-scan-production.md`

`scripts/dual-node.sh handoff --align-git mac` 已将云端工作树快进到 `fbdba7880af47d26ade13186928c8fd35792e0d4`。脚本后续本地 API 预检因 Mac `127.0.0.1:8000` 未启动而返回 connection refused；Git 快进已完成，该预检不涉及 Tushare worker 或云端服务。云端 `refs/remotes/origin/master` 随后以旧值作为 compare-and-swap 原子对齐到同一提交。

云端 `dual_node_check --node cloud` 通过：`drift={}`、`errors=0`、`peerCompletion=100`、`peerNeedItems=0`。`tushare-research-cache.timer` 为 active/enabled，云端全量 `archive/full/writer` unit 数量为 0。Mac 继续独占 Tushare 供应商采集和全量归档写入；云端只保留受限研究缓存，没有复制或启动全量数据库。
