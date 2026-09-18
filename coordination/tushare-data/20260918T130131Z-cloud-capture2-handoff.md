# Tushare 双路隔离采集云端交接

- 时间、节点、任务标识：2026-09-18，cloud，capture2
- 状态：代码和生产验收记录已对齐；云端角色不变
- 接续：`20260918T125959Z-mac-capture2-production.md`

`scripts/dual-node.sh handoff --align-git mac` 已将云端工作树快进到 `09e277f4369296fb5b72ded80b937f5bfe3442f5`。脚本末尾仅因 Mac `127.0.0.1:8000` 未启动而返回本地 API connection refused，Git 快进已完成；云端 `refs/remotes/origin/master` 随后使用旧值作为 compare-and-swap 原子对齐到同一提交。

云端 `dual_node_check --node cloud` 通过：`drift={}`、`errors=0`、`peerCompletion=100`、`peerNeedItems=0`。`tushare-research-cache.timer` 为 active/enabled，云端全量 `archive/full/writer` unit 数量为 0。双路采集只在 Mac 私有配置中生效；云端没有获取 Token、全量数据库或供应商写入能力。
