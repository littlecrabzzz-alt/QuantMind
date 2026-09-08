# 双端数据：自动更新与拉取
- 状态：进行中；Mac；基于 e4a5212，独立分支 codex/automatic-data-refresh。
- 分工：market_sync_scheduler.py 及对应测试；dual_node_snapshot.py、dual_node_check.py 和快照部署配置/测试；现有双端数据文档。Tushare 采集/镜像沿用已部署实现，不占用其实现文件。
- 用户授权：开启云端 A 股定时更新，并定时从云端拉取数据；worktree 不同步。
- 方案：复用 Celery 的市场配置、现有完整快照与 SSH 拉取入口、systemd/launchd；后台仅更新下载区，已有沙盒仍固定 SNAPSHOT_ID。Tushare 已每 120 秒采集、Mac 每 900 秒拉取，实际后台 exit 0。
- 验证起点：handoff passed，三端 HEAD e4a5212，4249 个源码/配置文件一致。保留全部未提交研究文件。
