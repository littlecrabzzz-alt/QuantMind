# QuantDB 恢复：实际数据与小时客户端验收通过

- 时间：2026-09-12 北京时间；节点 Mac；任务 01a08195-023e-7bd1-a36d-ad71c0cac786。
- 接续并更正 [开始记录](20260911T151423Z-mac-quantdb-recovery-80189372.md)。此前“已启用同步”没有完成本地实际数据验收，不等于已追平。
- 代码已合入 master 至 09017f6f；候选分支 codex/quantdb-recovery。后续云端消费者/Beat 恢复和最终 Git/内容交接由任务 01a0817d-7378-7673-9b7f-59c302713981 统一负责。

原因与修复：云端单并发 worker 被重复超时的 US 作业占用；完整快照连续跳过/停用，本地下载流程又没有应用新 QuantDB。现有 worker 增加市场队列、避免失败任务无限重投、当天错过时刻补派；复用现有快照校验/增量传输，仅发布 QuantDB Parquet，在本地空闲时补行情和 Qlib。Mac 挂载别名已校正，Qlib 在新目录构建校验后由 Mac 宿主原子发布，保留旧数据；失败重试保持原备份并只续做派生更新。规则复用 [AGENTS.md](../../AGENTS.md)、[数据写入规范](../../docs/development-data-contract.md)，未新增第二套协作规范。

实际验收：
- 云端采集 qdb-celery-20260911-231753 完成：23 个数据集、2697 个文件下载、0 下载错误，PG 补 49981 行、0 失败批次；QuantDB/PG/Qlib 至 2026-09-11。附属北/南向模块缺失仍是独立缺口，不声称所有外部来源完成。
- 发布并下载版本 snapshot-quantdb-20260911T155142529396Z：117133 文件、55163849769 逻辑字节，完整校验通过，实际网络接收约 612 MB，复用原不可变快照。
- 本地 `.local-dev/QUANTDB_SYNC.json` 为 applied；本轮 PG 补 27791 行、0 失败批次；真实数据读取器、PG、Qlib 日历均至 2026-09-11。当天 5562 行，SH600036=41.35、SZ000001=11.74，Qlib 还原价和云端 JSON 一致。控制台实际统计的前复权/不复权/指数日线最新日也均为 20260911。
- 原 QuantDB 备份 `.local-dev/quantdb-before-20260911T160817-7f4d72`；旧 Qlib `.local-dev/qlib-before-82174acde8ea43c3bb38bd5976d7ff1c`。236591 个本地结果/模型/固定输入文件 SHA256 核对 0 变化，研究 settings 和冻结输入 manifest 不变。本地 API、研究 worker 恢复 healthy。
- 现有 com.quantmind.snapshot-pull 客户端已重装，脚本与主树 hash 一致，每 3600 秒。首次真实 launchd 运行 exit 0：云端同版本检查、下载已验证、本地已应用、完整基线已验证。日志位于 `~/Library/Application Support/QuantMind/logs/snapshot-pull.*.log`；不依赖聊天保持开启。
- 回归：市场调度 11 项、QuantDB 刷新 9 项、部署安全 23 项（1 项明确要求实际 Docker 的测试跳过）通过；真实 Mac apply 和两端 readback 单独完成。

边界：这是正式 QuantDB 单向更新到本地沙盒。完整业务库基线仍为 snapshot-20260908T134413970428Z，固定研究输入不自动换版，本地成果不回灌。旧主树 data/quantdb 属迁移基线，实际运行读取 `.local-dev/project/data/quantdb`；不要为追平而启动旧完整服务栈。Mac 休眠/离线、后端停止、活动任务或本地修改冲突时延后应用并保留数据，恢复条件后重试。公网及 Tushare 新需求未扩入本轮。
