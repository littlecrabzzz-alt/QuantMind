# Tushare 云端采集与 Mac 镜像验收

2026-09-09，北京时间。范围沿用 [总计划](tushare-integration-plan.md)，操作入口见 [运行手册](tushare-intake-runbook.md)。已跑通七个 RRG 接口的采集、存储、发布、同步和离线读取；全目录覆盖与 RRG 数据准入尚未完成。

## 实际部署

- 采集代码与云端配置：master b15932a；Mac 后台客户端修复：1a7a314，均通过主分支集成。数据始终由 lzy-vm 的现有云端环境写入 `/data/tushare`，SSD 宿主路径为 `/root/data/disk/quantmind/project/data/tushare`。
- 新增 `quantmind-tushare-worker`，独立 `tushare_acquire` 队列，单并发、1 GiB、0.75 CPU，复用已有镜像/Redis。实际挂载和 authority 角色核验通过，健康检查通过。
- 重建现有 beat，使云端角色和 120 秒调度生效；原行情/研究 worker 没有重启或中断。00:19:26 自动发送并接收任务 `0a9903cd-c0dd-48c2-82ca-4eb20334b2ef`，00:20:37 成功完成 100 个请求，耗时 70.66 秒；00:21:26 下一轮自动接收。
- 云端配置 `/data/tushare/pipeline-config.json`，已启用 `/data/tushare/ENABLED`。历史请求起点 1990-01-01、2020 年以后优先，不把请求起点说成供应商确有数据。
- Mac LaunchAgent `com.quantmind.tushare-mirror` 每 900 秒同步。最初直接运行 Documents 脚本的后台进程卡在打开脚本，已卸载；改为不含凭据的 Application Support 客户端副本后，真实后台运行正常退出（exit 0）。代码更新后重新安装客户端，不由数据同步器更新代码。
- Mac 当前镜像：`~/Library/Application Support/QuantMind/tushare`；运行文件：相邻 `tushare-client/`；后台日志：相邻 `logs/`。原 `QuantMind/logs/tushare-mirror` 保留首批手动验收副本。源码/配置仍用 Syncthing；数据仅以不可变清单经 SSH/rsync 从云端单向拉取，活动 SQLite 不复制。

## 固定版本与真实检查

固定版本：`data-da65229f4585148bd96c4b0f97a6c60113885523d9c268598c482aac1a63b3f5`。

该版本共 575 个原始对象/观察记录/Parquet 文件。队列记录：190 done、1 quality、1 empty、42371 pending。待采集数随交易日发现而增加，不能把它当固定总数估算已完成比例。done 仅代表请求分片通过当前检查，不代表历史或 PIT 完整。

| 数据 | 固定版本去重行数 | 已观察时间范围 |
|---|---:|---|
| 中信行情 ci_daily | 27089 | 2020-01-02～2026-09-08，行业/年度尚未全齐 |
| 中信成分 ci_index_member | 6740 | Y/N 按 30 个一级行业请求，历史可知时间未验证 |
| ETF 基础 etf_basic | 1829 | L/D/P；在市数据仍有上市日期缺失 |
| 基金复权 fund_adj | 2148 | 2026-09-07 |
| 基金日线 fund_daily | 2106 | 2026-09-08；原接口也可能含非 ETF 基金 |
| ETF 持仓 fund_portfolio | 339 | SH510300，2026-06-30 报告期；公告日 07-21～08-29 |
| 日历 trade_cal | 2443 | 2020-01-01～2026-09-08 |
| 合计 | **42694** | 尚非完整研究样本 |

- 首轮 13 请求落盘，复权分页 offset 0/1000/2000 实际返回 1000/1000/148，共 2148 行；没有把接口默认上限当成全部。
- 第二个独立进程从已有检查点继续完成 79 请求，未重拉首轮已完成历史任务；后续自动任务再完成 100 请求。近期修订有独立世代，会按计划重新检查。
- 云端与 Mac 对同一版本逐文件核验 SHA256/字节数，再禁止 socket.connect、DNS 与 get_secret 访问，七类数据均通过固定版本读取且行数、时间边界一致。证明的是新存储读入口，无修改现有 QuantDB/页面查询路由。
- 真实后台镜像下载该版本 575 文件，随后手动重复执行下载 0 文件；CURRENT 只在全量校验通过后更新。模拟中断、重试、无变化和损坏恢复分别有隔离测试；没有为故障测试破坏真实权威数据或网络。
- 隔离测试：7 项流水线测试、5 项原始留存测试通过，Ruff 通过。真实读取证据在两端镜像根目录 `validation/offline-<release_id>.json`；云端首两轮证据为 `validation/pipeline-first.json`、`pipeline-second.json`，动态状态为 `pipeline-status.json`。

## 未完成与继续方式

- 全历史回填已持续运行，七类接口以外的目录条目、其他市场、九个独立授权文本 API 及 PDF 正文等仍按总计划接入。263 个目录条目与七个已实现接口分别记录，不能宣称全 Tushare 已同步。
- 当前缺口包含在市 ETF 上市日缺失，以及 CI005021 历史成员 N 的空响应；空值不被冒充为“无历史”。后续可能发现更多权限、截断、数据质量问题，保留清单后再审阅补齐。
- RRG 继续 `blocked_data`：完整行业历史、历史成分/基金池的 PIT 与可交易性、持仓敞口完整性仍须独立验收。首次抓取时间不倒填历史 known_at，未启动回测、模拟或实盘。
- 已下载版本脱离 Tushare 可读；Mac 断网或休眠不影响云端继续采集，恢复后下轮同步。Mac 未下载的缺口不会在查询时偷偷请求 Tushare。
- 数据不自动删除；每轮检查至少 100 GiB 可用余量，不足暂停并待扩容。检查时云盘约 324 GiB 可用，当前无需扩盘；后续仍须按实际增长/备份峰值复核。
