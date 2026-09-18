# index_weight 7000 行边界重评生产完成

- 时间、节点、状态：2026-09-18T22:11:00Z，Mac 全量归档唯一写入者；旧 1000 行阈值误报已修正并上线。
- 代码：候选 `e502af9e`、master `14541c19`。保留历史任务的 1000 行请求身份，采集和离线重评按生产实测的 7000 行边界判断；显式 `has_more=true` 仍视为未完整。
- 重评：91 个单日 blocked 任务逐项验证 raw object、observation 与 Parquet 哈希后转为 done；attempt 记录保持不变、上游请求 0。`index_weight` blocked 从 91 降为 0，6 个真实 `has_more=true` 响应仍保留分片义务。
- 验证：定向 53 项通过；完整套件 1386 项通过、5 项跳过，117.482 秒，日志 SHA-256 `31a64f357e3c559e6807570f093843bbe6fddeba8340cf42e2450c3986389fe5`；Ruff、编译和 diff check 通过。
- 部署：等待原周期自然完成并写出 disabled 后卸载，没有强杀；恢复相同 ENABLED SHA/0600 后安装 master。新 PID 61201、runs=1、last exit never，运行时三个修改文件与 source SHA 一致。
- 真实周期：104.869 秒完成 764 次 Tushare 请求和 1232 个文档任务，`failed_stage=null`。本地可用约 1.9 TiB；全量补采继续，云端仍只作为研究缓存。
- 证据：`docs/tushare-index-weight-cap-reassessment-production-20260919.json`。完整历史、空响应确认、修订、known_at 与 PIT 继续开放。

下一步：核验 `dc_member` 与 `moneyflow_dc` 旧无过滤日任务是否已经被新的逐标的范围计划完整覆盖；没有覆盖证据前不删除或伪装关闭这些缺口。
