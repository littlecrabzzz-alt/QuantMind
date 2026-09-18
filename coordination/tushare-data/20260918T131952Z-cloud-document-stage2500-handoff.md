# Tushare：文档阶段 2500 云端交接

- 时间、节点、任务：2026-09-18T13:19:52Z，cloud，document-stage2500-handoff
- 状态：Mac 生产验收后的代码与记录已交接到云端；云端角色未改变。

`scripts/dual-node.sh handoff --align-git mac` 已将云端工作树快进到 `7db492e97fdf69d5078aa353e97df795488e4669`。Mac 本地 8000 未启动，因此 handoff 的末端应用健康检查报 `Connection refused`；Git 快进在该检查前已完成。云端 `origin/master` 随后使用带旧值校验的 `git update-ref` 原子对齐，HEAD 与 `origin/master` 均为上述提交。

云端 `dual_node_check.py --node cloud` 结果为 `drift={}`、`errors=0`、`peerCompletion=100`、`peerNeedItems=0`。`tushare-research-cache.timer` 为 `active/waiting`，对应 service 当前 `inactive/dead` 是定时任务空闲态。云端没有 Tushare 全量归档、采集或镜像写入单元；它仍只从 Mac 全量归档取得受限研究子集/缓存。

Mac `com.quantmind.tushare-archive` 继续作为唯一全量写入者，2500 阶段档位的真实验收见 `20260918T131631Z-mac-document-stage2500-production.md`。
