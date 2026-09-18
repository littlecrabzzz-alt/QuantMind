# Mac Tushare 成功周期空档灰度生产验收

- 候选 `00900563` 已合入 master `8fc312d2`。仅成功且非 `planning_only` 的周期把最短休眠从 5 秒降为 1 秒；规划轮仍为 5 秒，失败/blocked/disabled/锁冲突等非成功状态保持至少 5 秒或原周期退避，账户/API/每日限额未改。
- 验证：`test_tushare_archive_worker.py` 9 项及 `test_tushare*.py` 1356 项通过（104.495 秒），Ruff、py_compile、diff check 通过。全套日志 `/tmp/qm-tushare-full-suite-success-gap.log` SHA-256 `e5c14bf854664c20075bc6a8e72adb769676516f77317a7162407f6eb9711f34`。
- 安全部署：旧 worker 自然进入 disabled 后更新；新 PID 95676，ENABLED/配置哈希和 archive.env 0600 保持，运行脚本/source SHA 均为 `27a2bf2e…`。
- 灰度实测：4 个真实周期共 3014 次请求，attempt rowid 759900–762913 全部 HTTP 200；1610 sample_ok、1396 empty_unverified、8 possibly_truncated，零 rate-limit/transport/API/permission/invalid 错误。中间一次到期规划轮请求数为 0，按设计保留 5 秒。
- 两个不含规划轮的灰度起点间隔均约 105.009 秒；旧基线正常间隔中位数 107.726 秒，固定空档减少约 2.717 秒。短样本请求组合不同，灰度墙钟 RPM 中位数 420.25、旧基线 428.14，未据此宣称吞吐提升；保留变更是因为相同工作量下确定性减少空档且限速证据安全。基线/灰度报告 SHA-256 分别为 `3f853943…`、`b9375287…`。
