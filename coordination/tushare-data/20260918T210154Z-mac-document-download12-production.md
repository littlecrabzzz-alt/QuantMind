# Mac Tushare 文档 12 路下载生产验收

- 时间、节点、状态：2026-09-18T21:01:54Z，Mac 全量归档所有者，12 路下载已验收并保留；全量历史同步继续。
- 代码：候选 `42622309`，master `cf541531`；只把原有有界下载并发的配置上限从 8 扩到 16，生产配置为 12。每轮 2500 阶段/100 秒、单文档 20 秒/256 MiB、持久 claim、失败退避、来源保护、PDF 解析边界和 Tushare 分层限速均未改。
- 测试：定向 48 项及 31 个子用例通过；完整 `test_tushare*.py` 为 1373 项及 1040 个子用例通过，99.86 秒，日志 SHA-256 `058174712c61fdfe31cc14cac56bc0130b59a32a250560ba288866ef7b2623cf`；Ruff、编译和 diff check 通过。
- 部署：原子移出 `ENABLED`，等待在途周期提交并明确写出 `disabled`，确认无任务子进程后卸载、安装 master 运行副本并恢复完全相同的 marker。新 PID 59914，`runs=1`、`last exit code=(never exited)`；运行副本与 master 的 documents/worker SHA 一致。
- 实测：8 路相邻 6 轮平均/中位为 2025/1997 阶段；12 路 6 轮共 14422 阶段，平均/中位 2403.667/2390，分别提高 18.7%/19.68%。同期 4639 次 Tushare 请求全部 HTTP 200，六轮 `failed_stage=null`，stderr 增长 0，进程树最高约 164 MiB RSS，系统 `Pages throttled=0`。
- 失败分类：精确时间窗内 12 路的 7343 下载中 7294 成功，非成功 49；对照 8 路的 6159 下载中 6101 成功，非成功 58。超时、HTTP 错误和解析失败未因并发增加。
- 证据：`docs/tushare-document-download12-production.json`。当前 Mac 仍是唯一全量 writer，云端只保留研究缓存；本记录提交后再执行 Git/云端代码对齐，不恢复云端全量采集。
