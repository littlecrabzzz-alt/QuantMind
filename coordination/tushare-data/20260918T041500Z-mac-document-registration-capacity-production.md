# Mac Tushare 附件登记追赶容量生产验收

- 时间、节点、任务：2026-09-18T04:15:00Z，Mac 全量归档所有者，document-registration-capacity。
- 代码：`f5a1905d` 让 tick 从私有配置向 `register_documents` 传入 observation、record、seconds 三项有界预算，并在状态报告回显实际预算。旧默认保持 20/500/5；代码硬上限为 1000/5000/20，超界与布尔/浮点伪整数直接拒绝。
- 验证：登记断点、文档先提交后 checkpoint、重放幂等、读写锁延后、单 SQL 中断、tick 时序与全局管线共 27 项测试通过；Ruff、示例 JSON 解析与 `git diff --check` 通过。

生产部署与配置：

- 旧 PID 21330 在 2026-09-18T04:10:24Z 完整结束 755 次真实请求、274 个附件阶段、`failed_stage=null` 后安全卸载。
- 私有配置加入 `document_registration_max_observations=100`、`document_registration_max_records=5000`、`document_registration_max_seconds=5`；附件下载仍为三路、每轮最多 600 阶段/100 秒，Tushare API 频率不变。配置 SHA-256 为 `c214c3e7cddd436822519f7e965a812c833b15a138a8c27edfdc7ced7d2f5f13`，权限保持 0600。
- 新 LaunchAgent PID 29460 的 pipeline 安装副本与仓库 SHA-256 均为 `3ad0e5ecd194e3de51c0685e3a47d270b1db704a0f3138639f7fce3f7780ab4a`，`runs=1`、`last exit code=never exited`。

真实生产验收：

- 首轮到期 planning-only 按预期没有运行登记器，只处理本地计划和 216 下载 + 214 解析，`failed_stage=null`。
- 紧随其后的真实 acquisition 在 104.269 秒完成 762 次 Tushare 请求、240 下载 + 238 解析，`failed_stage=null`。登记状态回显 100/5000/5，在 2.946004 秒处理 5000 条记录、扫描 2 个 attempt、完成 1 个 observation；游标从 176179 推进到 176180，并在 attempt 176181 的 record offset 4114 建立合法 partial checkpoint。
- 旧代表轮在 0.481441 秒处理 500 条记录；新轮把每周期记录容量提高 10 倍，实际登记吞吐约从每秒 1039 条提高到 1697 条。周期总长仍接近既有 105 秒基准，没有降低该轮 762 次 API 吞吐。
- `source_challenge` 保持 5275；本地剩余空间 2479217111040 字节。数据库忙、截止或崩溃仍按原断点语义重放，不把未登记记录视为完成。

登记器会继续追赶剩余 attempt，附件下载 worker 同时消费已登记队列。Mac 仍是唯一全量 writer，云端仍只保留研究子集。
