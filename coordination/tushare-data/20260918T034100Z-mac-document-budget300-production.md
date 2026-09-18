# Mac Tushare 附件 300 阶段预算生产验收

- 时间、节点、任务：2026-09-18T03:41:00Z，Mac 全量归档所有者，document-budget300。
- 变更范围：Mac 私有 `pipeline-config.json` 仅把 `document_worker_max_documents` 从 240 调到 300；`document_download_workers=3`、`document_worker_max_seconds=90`、单 Tushare HTTP worker、500 次/分钟账户与灰度上限、磁盘保护和失败退避均未改变。配置 SHA-256 为 `b74809198b80e987db301587d0e1f0355d38d521f10a26b99f53bd485288d38f`，worker 按周期读取，未重启。
- 运行性质：这是正式队列上的生产灰度，不是模拟或 dry-run。planning-only 周期只整理本地队列，不调用 Tushare；其余观察周期均执行真实 Tushare 采集并写入本地全量归档。

完整周期观察：

- 一轮 planning-only 周期处理 132 下载 + 130 解析，共 262 阶段，耗时 90.082 秒，上游请求 0。
- 五轮真实 acquisition 周期分别完成 764、760、660、661、734 次 Tushare 请求；结构化 pending 从 2881404 降到 2878673，所有周期 `failed_stage` 均为空。
- 同期附件分别完成 126+124、150+150、150+150、120+118、141+142，共 250、300、300、238、283 阶段；真实周期平均下载 137.4 份，相对原 120 下载上限提高约 14.5%，网络较快的两轮达到 150 下载，提升 25%。
- API 请求数在 660 至 764 间波动。661 请求的周期只完成 120 下载，未超过旧 240 阶段上限；因此低请求周期不能归因于 300 阶段预算本身，但当前观察也不足以声称附件提速完全不影响 API 吞吐。保留 300，不再提高并发或时间预算，继续生产观察。
- `source_challenge` 保持 5275；验收时其他下载分类为 download_error 4、download_timeout 74、http_error 35、invalid_url 26、pdf_content_mismatch 1273、size_limit 446、unsupported_or_invalid_document 125。没有绕过来源挑战或失败退避。

验收边界状态：LaunchAgent PID 7728 仍为启动以来同一进程，`last exit code = never exited`；最新完整周期于 2026-09-18T03:40:01Z 完成，结构化队列 done 290989、empty 254825、pending 2878673、blocked 871。附件为 pending 1484683、retry 18、parsed 40230、parse_pending 71812；本地剩余空间 2481772285952 字节。全量采集继续运行，本记录只确认 300 阶段预算可保留，不表示全量同步已经完成。
