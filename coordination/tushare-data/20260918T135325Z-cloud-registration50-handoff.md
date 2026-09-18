# Mac Tushare 附件登记 50 档云端交接

- 时间、节点、任务：2026-09-18T13:53:25Z，cloud，registration50-handoff
- 状态：Mac 私有配置灰度的生产验收记录已交接到云端；云端数据角色未改变。

`scripts/dual-node.sh handoff --align-git mac` 已将云端工作树快进到 `68a0044e855dbefc1df0028526497bf55bb6c74d`，云端 `origin/master` 使用带旧值校验的 `git update-ref` 原子对齐。Mac 本地 8000 未启动，handoff 末端应用检查仍报 `Connection refused`，Git 快进已在该检查前完成。

云端 `dual_node_check.py --node cloud` 结果为 `drift={}`、`errors=0`、`peerCompletion=100`、`peerNeedItems=0`；`tushare-research-cache.timer` 为 `active`。云端仍未启用 Tushare 全量 writer，Mac 继续作为唯一全量归档写入者。

50 档保留持久游标且连续净追赶 attempt，真实周期吞吐验收见 `20260918T135153Z-mac-registration50-production.md`。
