# Mac Tushare 三路采集云端交接

- 时间、节点、任务：2026-09-18T13:38:16Z，cloud，capture3-handoff
- 状态：Mac 三路采集生产验收后的代码与记录已交接到云端；云端数据角色未改变。

`scripts/dual-node.sh handoff --align-git mac` 已将云端工作树快进到 `7d26901e0915cee3644949dcaccb2be10bec3197`，云端 `origin/master` 使用带旧值校验的 `git update-ref` 原子对齐。Mac 本地 8000 未启动，handoff 在 Git 快进后的应用健康检查报 `Connection refused`，不影响已完成的源码/Git 交接。

云端 `dual_node_check.py --node cloud` 结果为 `drift={}`、`errors=0`、`peerCompletion=100`、`peerNeedItems=0`。只有 `tushare-research-cache.timer` 为 `active/waiting`，对应只读缓存 service 当前为正常空闲态；没有 Tushare 全量归档、采集或镜像写入单元。

Mac `com.quantmind.tushare-archive` 继续作为唯一全量写入者，真实吞吐、attempt 错误分类和资源验收见 `20260918T133649Z-mac-capture3-production.md`。
