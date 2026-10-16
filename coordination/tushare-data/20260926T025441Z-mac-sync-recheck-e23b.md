# 数据同步只读复查：云端 PG 阶段 OOM

- 时间、节点：2026-09-26 10:48–10:54 CST，Mac 发起，云端只读核验。
- 状态：复查完成，故障未修复。主工作树 HEAD `e23b6712`；双端 handoff 通过。保留所有既有未提交修改。
- 分工：只新增本记录；未修改代码、配置、数据指针，未重启服务或补跑同步。
- 接续：[重点研究数据独立发布完成](20260925T021035Z-mac-research-publication-complete.md)。

| 链路 | 本次实测最新日期 | 结论 |
| --- | --- | --- |
| Mac Tushare 六个核心日频接口 | 2026-09-24 | 最新成功任务、Parquet 日期及 SHA-256 核验通过；采集和供数 LaunchAgent 均运行 |
| 云端 Tushare 固定版本读取 | 2026-09-24 | daily 5557 行、moneyflow 5569 行；版本滞后，不能视为追平源端 |
| 云端 QuantDB 原始文件 | 2026-09-24 | daily_unadjusted、daily_forward、index_daily、l1_factors、valuation 最新分区一致 |
| 云端 PG / Qlib 日历 | 2026-09-23 | 仍落后一个交易日 |
| 云端市场分析 | 2026-09-24 | 当前产物日期已到最新交易日 |
| Mac 沙盒 PG / Qlib / 市场分析 | 2026-09-24 | 从容器实际读取；本地派生数据日期已追上 |

交易日依据：云端固定版本 trade_cal 返回 9/24 is_open=1、9/25 is_open=0；[上交所休市公告](https://www.sse.com.cn/disclosure/announcement/general/c/c_20260915_10832273.shtml) 确认 9/25–27 休市、9/28 开市。因此 9/25 的 empty_unverified 采集结果与休市相符，不作为漏采证据。此次没有复核全历史覆盖率或既有研究固定输入。

Tushare 证据：

- Mac 核心源文件行数：daily 5557、adj_factor 5569、daily_basic 5557、stk_limit 5648、suspend_d 13、moneyflow 5569；本次所查成功观测时间为 9/26 00:17 CST。临时逐文件核验结果 `/tmp/quantmind-native-core-verified-20260926.json`。
- 云端固定读取 release：`data-c8075a2696cc635abbf96f8f95fa471c6d8e07762671a20e557157c2daf6b506`；对应源 `data-e808df52fd8220ec29418da83c393239da73a7f731802da026af6a30ee4c0b03`。
- Mac 新研究源：`data-ec9d25c4b8110573b98178125d15c37c85c9cbd8a2d48116a230ae68f8f4d327`，10:35:47 发布；对应新子集 10:41:44 准备完成。
- 云端 timer active；最近拉取 10:41:26–10:45:10，exit 0、cache-status verified，但 `source_lagged=true`。本轮返回已验证旧子集，新版准备晚于拉取请求。当前缓存 22,764,690,697 字节，预算 50 GiB。

QuantDB 故障证据：

- 定时配置仍为 A 股 03:00、enabled=true、with_qlib=true；9/26 03:00 日志确认派发。
- 03:11:24 进入 `Phase 2: Fill PG from parquet`，增量起点 9/16、PG 最大日 9/23。
- 03:13:12 内核记录 `CONSTRAINT_MEMCG`、`Memory cgroup out of memory: Killed process ... (celery)`；03:13:13 同一作业出现 SIGKILL / WorkerLostError。
- 内核 cgroup 对应当前 quantmind-celery 容器 ID `0563e98e770d7f9484991ccbbd3f4bd59943a9f907a9ab7d719fe71c98613062`；容器内存限制 1.5 GiB。容器整体 OOMKilled=false 不代表其子 worker 未被 OOM 杀死。
- 当前 PG 转换按全市场回看 160 自然日，DuckDB fetchdf 后做 Pandas 派生指标及 object 转换；这是需要进一步控制的内存峰值路径，具体峰值函数尚未测量。Qlib 位于该阶段之后，本次没有进入。
- 次要问题：同批日志北向、南向同步均报告对应脚本模块不存在；未修复，不能将其列为已成功同步。
- Mac `.local-dev/QUANTDB_SYNC.json` status=applied，原始快照 `snapshot-quantdb-20260925T211728455924Z`；PG 跳过原因仅为 9/25–26 无新增交易日，实际 PG/Qlib 已为 9/24。本地与云端结果分开核验。

下一步优先修复云端 PG 转换的内存峰值与失败恢复，然后只补 PG/Qlib 并核对日期、覆盖与代表标的。Tushare 后续按新子集实际切换验收；无需把本次问题转为全库重新采集。
