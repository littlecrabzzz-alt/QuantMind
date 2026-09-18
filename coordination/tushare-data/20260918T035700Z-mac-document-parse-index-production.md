# Mac Tushare 附件解析队列索引生产验收

- 时间、节点、任务：2026-09-18T03:57:00Z，Mac 全量归档所有者，document-parse-index。
- 代码：`493ad440` 把 document claim 元数据从 v2 事务升级到 v3，为 `downloaded` 且仍可重试的解析集合增加按文档 ID 排序的局部索引，并让解析领取显式使用该索引。网络下载、解析器、三路并发、90 秒截止、失败退避和 Tushare API 限速均未改变。
- 自动验证：文档下载、解析、并发、租约、证据、挑战分类、worker 与 archive worker 共 63 项测试通过；v1/v2 迁移失败均保持旧版本并可重试，查询计划断言不出现临时排序；Ruff 与 `git diff --check` 通过。

生产迁移与恢复：

- 旧 PID 7728 在 2026-09-18T03:48:42Z 完整结束一轮 726 次真实请求和 250 个附件阶段、`failed_stage=null` 后卸载，没有强停在途周期。
- 安装副本准备完成后，在唯一 writer 停止期间把生产 `documents.sqlite` 的 claim 元数据从 v2 升到 v3，索引创建与提交耗时 8.454505 秒。生产只读查询计划由 `document_parse_claim_order` 扫描且无临时排序；领取 1、3、24、48 行分别约 0.000108、0.000040、0.000527、0.000640 秒，旧索引前领取 1 行约 0.176535 秒。
- LaunchAgent 已恢复为 PID 21330，`runs=1`、`last exit code=never exited`；安装副本和仓库的 `tushare_documents.py` SHA-256 均为 `b75193e7d945832837d96e6ca6cdad3af9489f523f2d70c43ab23b9545911fce`。

真实周期验收：

- 首轮完成 759 次 Tushare 请求、150 下载 + 150 解析，300 阶段只用 41.627 秒；claim 总时间 0.183282 秒，`failed_stage=null`。
- 下一真实轮完成 746 次请求、150 + 150 阶段，附件耗时 67.194 秒、claim 0.183976 秒，`failed_stage=null`。索引前代表轮 claim 为 17.113577 秒。
- 节省的时间使 300 阶段重新成为上限，因此私有配置只把 `document_worker_max_documents` 从 300 调到 600；三路并发和 90 秒截止不变。配置 SHA-256 为 `3169fd100feb393215f2e8a3bb02843c81178ea084c0fbed642e5139e9d8f7e1`，权限保持 0600。
- 600 上限首轮 planning-only 完成 186 下载 + 184 解析，共 370 阶段；首轮真实 acquisition 完成 723 次请求、162 下载 + 160 解析，共 322 阶段，`dispatch_rejections=0`、`failed_stage=null`，claim 0.203887 秒。600 是时间截止内的容量上限，不保证每轮处理满额。
- `source_challenge` 保持 5275；没有绕过来源保护。验收边界结构化队列 done 293955、empty 256944、pending 2880338、blocked 871、permission_blocked 4694。规划会继续发现和登记任务，因此 pending 与附件 pending 可能阶段性增加，不能把单轮总量上升解释为回退。

Mac 继续作为唯一全量写入者，LaunchAgent 已恢复持续采集；云端仍只读研究子集。本次优化缩短本地附件队列处理路径，不改变双端数据拓扑。
