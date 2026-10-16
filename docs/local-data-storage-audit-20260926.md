# 本地采集、云端采集和存储复查（2026-09-26 晚间）

核验窗口：北京时间 23:35 起。代码 HEAD `de76004ad015faaae85e80ccdaccb932fc5a4407`，双端 handoff 通过。本次为只读运行检查，没有启停采集、修改调度或清理数据。归档持续写入，容量和队列数是检查时点值。

## 用户本轮确认的目标与实际差异

用户明确：数据同步以本地为主，云端不应继续承担上游采集。目标应统一为“本地唯一采集 → 校验版本 → 云端按需接收、派生与研究使用”。云端业务数据库的权威性与上游采集的位置是两件事；本地采集不意味着覆盖云端业务数据库。

当前仅 Tushare 符合这个采集方向。QuantDB A 股和 Binance BTC/ETH 仍有云端上游任务，这是待迁移项，不能描述为“已全部本地采集”。现有 `AGENTS.md` 的 QuantDB 云端采集描述反映当前实现，不能代替用户本轮确认的新目标。

迁移需先具备本地调度、失败恢复和唤醒补采，验证本地发布、云端接收及 PG/Qlib 消费，再关闭旧云端供应商调度，确保每个来源只有一个采集者。Mac 离线时云端保留已验证版本，不自动退回上游采集。当前不能仅关闭云端定时器就声称迁移完成。

## 每日更新和未接入的范围

| 数据 | 实际采集/同步位置与频率 | 当前验证 |
| --- | --- | --- |
| QuantDB A 股股票/指数日线、估值、技术指标、情绪与因子 | 云端每天 03:00 采集；Mac 每 15 分钟及唤醒后拉取 QuantDB Parquet 快照，空闲时应用 | 本地 receipt 为 applied；上述分区及本地 Qlib 日历到 2026-09-24；最近拉取判断版本未变化 |
| QuantDB 基础资料、财务数据 | 同一日常调度检查上游变化 | 财报按供应商披露节奏；融资融券分区到 2026-09-23，不伪装成全部数据统一日期 |
| Tushare 研究重点 | Mac 原生 worker 持续采集；15 接口研究子集约每 900 秒发布 | 六个核心按日接口最近非空日为 09-24；fund_daily 与 sw_daily 的 09-24 请求也已完成 |
| Tushare 其他结构化历史、公告索引、附件与正文 | 仍在 Mac 自动后台补采；完整归档约每 6 小时发布 | 不是只采研究重点；检查日 epoch 有 158 个 API 的计划，存在长队列，不代表 158 个全部日更完成 |
| QuantDB 分钟线、Tick、旧 ETF 行情目录 | 不在现有 23 数据集日常采集范围 | min1/min5/tick 和旧 etf_kline 均仅见 2026-09-03 分区 |
| BTC/ETH | 云端 BC 调度启用，每天 08:15，最近 5 天重叠，更新日线/交易对及 Qlib | Mac 只有固定版本，无云端新版本自动回传；本地与已验收云端日线截止 2026-09-25 UTC |
| 今日扩充币种、股票代币、股票永续 | 一次性补录与固定版本发布 | 不属于 BTC/ETH 日更池，没有新增本地日更或自动回传 |
| QuantUS/QuantHK/独立期货研究数据链路 | 云端 US/HK/FUTURES 定时 enabled=false；本地没有对应完整自动拉取链路 | Tushare 的部分港股/期货/海外基础数据补采与这些研究库独立，不能相互替代 |
| 云端完整数据库/恢复快照 | 本地按需下载，不是每 15 分钟全库同步 | 本地完整快照仍是旧基线；QuantDB 有独立增量快照链路 |

QuantDB 23 个日常数据集：

- 日线：daily_unadjusted、daily_forward、daily_backward、index_daily。
- 基础资料：sector_concept、instrument_detail、index_weights、trading_calendar、margin_trading。
- 财务：balance、income、cashflow、capital、pershare_index、dividend_factors、holder_num。
- 派生与因子：valuation、technical_indicators、market_sentiment、features_daily、l1_factors、l2_factors、l1_l2_factors。

Tushare 15 个重点发布接口：daily、index_daily、fund_daily、adj_factor、daily_basic、index_weight、ci_daily、sw_daily、stock_basic、index_basic、fund_basic、trade_cal、stk_limit、suspend_d、moneyflow。重点发布集合不等于本地全部采集集合，也不保证这些接口的历史均完整。

原生配置仍启用财报、股东/公司事件、资金流、融资融券、ETF 篮子、期货、债券、期权、外汇、宏观、公告正文等家族；`enable_foreign_financial=false`。权限记录显示港美财务/部分复权数据、多类分钟与实时接口仍被拒绝；部分旧文娱接口由供应商报告不可用。指数历史权重、基金净值、港股历史等仍有 pending，不能归为已完整采集。

## 存储核验

- Mac 数据卷总容量约 3.6 TiB，已用约 79%，23:35 可用约 788 GiB，23:45 约 785 GiB，23:47 约 789 GiB。运行中余量存在波动，压力判断以连续日志和保留阈值为准。
- 同一 worker 的全盘余量日志：09-24 23:29 为 1113.73 GiB，09-25 23:29 为 910.44 GiB，09-26 23:30 为 788.68 GiB。约 24 小时减少 121.76 GiB、约 48 小时减少 325.05 GiB；这是全盘净变化，不能全部归因于 Tushare，也不能直接当稳定日增速。
- Tushare releases、archives 和研究导出中的 JSON 清单，按设备/inode 去除重复硬链接后约 135.06 GiB；其中今天修改的文件约 24.61 GiB。包括历史版本清单，不含所有行情/附件内容。
- Tushare documents.sqlite 约 38.53 GiB，pipeline.sqlite 约 20.05 GiB；正文下载队列仍约 1329 万项。这些不是研究启动前必须清空的队列。
- `.local-dev` 的目录统计约 718.42 GiB，含当前项目约 97.90 GiB，以及 10 份 QuantDB 更新前备份（目录统计约 616.75 GiB）。备份使用 APFS clone，共享块可能重复计入，不能据此承诺删除后回收 616.75 GiB。
- 主目录旧 `data` 约 50.95 GiB；Docker 虚拟磁盘已分配约 54.92 GiB。Docker 总量包含其他应用，且相关镜像/卷统计不能与磁盘文件重复求和。
- 云端数据盘约剩 459 GiB；Tushare 研究缓存约 24.06 GiB / 50 GiB 预算，已验证但 `source_lagged=true`。缓存预算不是本地完整归档预算。
- 原生 worker 实际实施 500 GiB 迁移提醒和 300 GiB 停止新采集/下载保留线；当前未触发。此保护不等于全盘所有程序都受同一阈值约束。

完整归档包含大量小文件；本次停止了耗时的全目录递归统计，只报告已完成的目录/清单统计及文件系统真实余量，不提供未经完成核验的 Tushare 全目录总量。停止的是本次只读统计进程，原生采集 worker 保持运行。不同目录存在硬链接和 APFS clone，以上目录值不得简单相加解释整盘占用或可回收空间。

当前尚有运行余量，但近期增长需要处理。收敛顺序应围绕研究需要：保留核心日频量价/因子，行业和 ETF 按课题补齐；先降低非当前课题全文/跨资产长历史补采，再按固定研究输入引用关系设计版本回收或迁移 NAS。不要无差别删除历史归档、快照或正在被研究引用的版本。

## 证据入口

- 本地 LaunchAgent：archive/source 运行中；snapshot-pull 已加载且最近退出 0；旧 mirror/frozen/precopy 未加载。
- 本地 `~/Library/Application Support/QuantMind/tushare/{pipeline-config.json,pipeline-status.json,archive-worker-status.json,pipeline.sqlite}`。
- 本地 `.local-dev/QUANTDB_SYNC.json`、实际 QuantDB 分区、本地 Qlib calendar；`~/Library/Application Support/QuantMind/logs/snapshot-pull.out.log`。
- 云端容器实际 `get_all_schedules()`：A/BC=true，US/HK/FUTURES=false。
- 云端 `/data/tushare-research/cache-status.json`。
- 今日 Binance 发布范围见 `docs/binance-data-cloud-acceptance-20260926.md`、`coordination/binance-data/20260926T073400Z-mac-batch-complete.md`。
