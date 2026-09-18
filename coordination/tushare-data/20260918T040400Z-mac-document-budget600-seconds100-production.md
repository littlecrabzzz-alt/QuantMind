# Mac Tushare 附件 600 阶段、100 秒生产容量验收

- 时间、节点、任务：2026-09-18T04:04:00Z，Mac 全量归档所有者，document-budget600-seconds100。
- 依据：解析领取索引上线后，300 阶段周期只需 41.627 至 67.194 秒，阶段上限再次先于 90 秒截止触发；结构 acquisition 同期通常约 100 秒。继续保持三路下载并发、单下载 20 秒预算、失败退避、磁盘保护和全部 Tushare API 限速不变。
- 配置：先把 `document_worker_max_documents` 从 300 调到 600，再把 `document_worker_max_seconds` 从 90 调到 100；均为 0600 私有配置的原子替换，worker 按下一周期读取，没有重启。最终配置 SHA-256 为 `89cb040e88c88bffee5ade465e6f9fb3d98fe54a3b9a74855e9dbc0763ad1775`。

生产证据：

- 600/90 的首轮 planning-only 完成 186 下载 + 184 解析，共 370 阶段；首轮真实 acquisition 完成 723 次请求、162 + 160，共 322 阶段，`dispatch_rejections=0`、`failed_stage=null`。
- 600/100 的首轮 planning-only 完成 285 下载 + 283 解析，共 568 阶段，附件耗时 100.288 秒、claim 0.575483 秒；这类周期只处理本地队列，不调用 Tushare。
- 紧随其后的真实 acquisition 在 101.810 秒内完成 764 次 Tushare 请求、174 下载 + 172 解析，共 346 阶段；`dispatch_rejections=0`、`local_quota_deferrals=0`、`failed_stage=null`，附件 claim 0.262594 秒。延长附件预算没有超过原有结构采集周期量级，也没有降低该轮 API 吞吐。
- `source_challenge` 保持 5275；没有绕过来源保护。验收边界附件 pending 1485659、retry 23、parsed 40230、parse_pending 73271；规划和结构采集仍会发现新附件，因此 pending 暂时上升不等于 worker 回退。
- 600 是容量上限，100 秒是绝对阶段预算；下载延迟较高时实际处理量会低于 600。按首轮真实 174 下载/约 105 秒折算约 14.3 万下载/日，但供应商登记新增、来源延迟、Mac 休眠和失败分类都会影响最终时间，不能作为完成承诺。

LaunchAgent PID 21330 持续运行，Mac 仍是唯一全量 writer，云端仍只保留研究子集。当前本地剩余空间 2476991922176 字节，全量同步继续。
