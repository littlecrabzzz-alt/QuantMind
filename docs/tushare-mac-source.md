# Tushare 归档、研究供数与恢复

用途：维护 Mac 唯一归档写入者及本机固定版本读取。本文说明代码合同和操作前置条件，不证明当前服务已启动、配置已应用或历史已采齐。主业务使用 Library 中的 `primary-runtime-*` 代码快照，Main 工作树用于开发；Tushare 原生客户端独立安装在 Library，不由主业务容器重复采集。市场编排与状态入口见[本地市场数据源](local-market-source.md)；附件合同见[原文与附件生命周期](tushare-document-storage.md)。

## 归档与自动范围

- 完整归档默认根为 `~/Library/Application Support/QuantMind/tushare`，独立于 `.local-primary` 和 `.local-dev`。`ARCHIVE_AUTHORITY.json`、写入者身份和 `ENABLED` 共同约束唯一写入；持久停写栅栏不得删除来绕过所有权检查。
- `config/tushare-local-research-only.json` 是合并覆盖项，不是完整运行配置：限定 18 个自动接口、300 秒原生轮次、每小时研究发布和每日全归档发布，关闭文档与目录自动采集。应用前核对实际 `pipeline-config.json`；不能据模板宣称现场同样配置。
- 缩减范围时先关闭旧 `enable_*`，再合并白名单；仅停 planner 不会排空旧任务，`collection_api_names` 还约束自动派发。保留凭据、频控、检查点及历史队列；未启用接口不等于没有合同或历史数据。
- `objects/` 保存原始响应，`observations/` 保存请求和观测，`parquet/` 保存分区；`releases/` 和 CURRENT 表达固定发布，SQLite 表达可恢复队列。不要复制活动 SQLite、清空 attempts、重置历史游标或改已发布文件来“修复进度”。

## 日常检查与版本读取

读取归档根下 `archive-worker-status.json`、`pipeline-status.json`、`RESEARCH_CURRENT.json` 与 `CURRENT.json`，分别判断轮次、失败阶段和实际发布版本；后台日志位于相邻 `logs/tushare-archive.*.log`。`planning_only` 会持久化任务但不发上游请求；`publish_only` 只发布已有观测。两者不能计为采集吞吐。

在具备 DuckDB/PyArrow/httpx 的环境，对明确固定版本执行：

```sh
python3 scripts/tushare_pipeline.py status --root /absolute/archive
python3 scripts/tushare_pipeline.py verify --root /absolute/archive --release-id data-实际ID
python3 scripts/tushare_pipeline.py query --root /absolute/archive \
  --release-id data-实际ID --api-name daily --limit 10
```

`verify` 可能遍历大量文件，应安排 I/O 窗口。reader 不回退上游；它读取已观察数据，保留原始代码、单位、未知字段和修订。`as_of` 约束本系统观察时间，不提供历史 PIT 保证。当前成员、单日样本、入队数或分页终页都不能单独证明历史全集。

## 安全升级与暂停

1. 移走 `ENABLED`，等待 pipeline/documents 写锁及在途请求自然排空；确认原生 worker 已退出后再覆盖安装副本，不强杀正在提交的请求。
2. 在 Mac Main 工作树执行 `python3 scripts/install_tushare_archive.py` 准备 `~/Library/Application Support/QuantMind/tushare-client` 持久客户端。默认只准备运行时，不启动采集；需要 uv 和已有依赖获取条件。Main 编辑不会自动更新该安装副本。
3. 私有凭据只放在 `tushare-client/config/archive.env`，权限 0600，使用 `TUSHARE_TOKEN`；不写入命令参数、发布清单、报告或同步载荷。
4. 归档所有权、完整性和私有配置已核实后，才执行 `python3 scripts/install_tushare_archive.py --activate --root /absolute/archive` 安装 `com.quantmind.tushare-archive`。已有 worker 时安装器拒绝覆盖。恢复 ENABLED 属于显式恢复采集，不是只读验证。

原生 worker 保留 300 GiB 余量，500 GiB 以下发容量预警；不足时停止新采集而非删除唯一归档。轮次默认 120 秒，可配置 105–3600 秒；模板覆盖为 300 秒。实际发布间隔以运行配置为准。WAL + FULL 的耐久边界不得用降低 synchronous 换吞吐；本机更换存储路径前须停唯一写入者，核对文件系统锁、SQLite WAL 语义及完整校验，不将移动目录当作自动完成切换。

## 频控、权限与失败恢复

账户 gate、API gate、供应商已观察冷却、每日总量都必须保留。`rate_policy=legacy` 是默认；显式 `tiered_v1` 仍受更严格合同/配置/已观察限制约束，未知 API 不因其他接口成功而提档。提高并发、规划预算或发布周期不增加供应商配额。

`cyq_perf` 的 `daily-quota.sqlite` 在请求前耐久预留，失败/超时不返还；损坏或时间回退失败关闭。它只覆盖同 root、同入口调用，不能代表全账户对账，删除账本不能恢复当天额度。权限积分和独立权益有到期边界，使用 `pipeline-status.json.rate_policy.entitlement`，不把购买记录或积分门槛当实际权限证明。

发生失败先保存状态和错误阶段，核对磁盘、authority、凭据权限、锁所有者与实际响应；不要用重置队列、抹除 permission gap 或扩大预算掩盖问题。低频权限复查只有真实成功才恢复对应 `api_name + src`，不外推到其他接口或来源。SQLite 状态缺失/损坏应保留原件并从一致备份制定恢复方案，不从固定研究子集重造全量采集检查点。

## 本机只读消费

主业务直接读取本机归档：`deploy/compose.local-primary.yml` 将
`QM_TUSHARE_READ_STORE` 设为 `archive`，通过 `QM_PRIMARY_TUSHARE_ROOT`
指定归档挂载源，默认即 Library 下的 `tushare`，容器路径 `/data/tushare` 为只读。
`QM_LOCAL_TUSHARE_ROOT` 属于独立沙盒配置，不能用它修改主业务挂载。

消费者记录明确的 release ID、清单和文件 SHA；不读正在构建的版本，不修改归档、
SQLite、配置或密钥。固定任务不随 CURRENT 自动切换；新发布、权限恢复与实际 reader
读取成功分别核验。读取已观察数据不提供历史 PIT 保证。

应用代码还接受 `research-cache` 读取模式，但这不是当前主业务的供数方式，
不据此创建新的缓存服务或第二条采集链路。已有固定输入若引用独立缓存，必须先核对
`source_release_id`、文件闭包与真实查询；`latest_source_release_id` 只表示已知最新版本，
`source_lagged=true` 的缺口不能由一次任务成功消除。旧固定缓存不自动删除。

更改主业务挂载或读取配置前先核对固定版真实查询，安排无活动任务的服务窗口，
按主业务实际部署配置核准重建，再验挂载源与只读标志；容器重启本身不改变挂载。
`scripts/local-dev.sh recreate-backend` 仅适用于独立沙盒，不是主业务操作。

## 本机归档恢复与空间维护

恢复前保留唯一写入者约束，停新请求并排空写锁；先保留原 SQLite、WAL、清单、
状态与日志，在隔离副本上验证一致 checkpoint、文件 SHA、观察记录和固定发布闭包。
恢复本机所有权与 ENABLED 前必须分别完成完整性、权限、容量及目标路径检查；
失败保留原件与恢复证据，不启动第二个写入者，也不从研究子集重造采集检查点。

附件退役后，保留文本或退役收据不能冒充旧 PDF 原件的逐文件保留证明；
恢复材料必须采用兼容实际退役状态的基线，不能重启旧镜像补回有意退役的 PDF。
业务库、冻结研究输入、完整恢复点和未知文件不因空间维护获得删除授权。

## 显式课题补采与固定版审计

普通 `tick` 会做全局规划/发现，不能保证下一个请求属于指定批次；提高 priority 也不证明精确范围。手动补采使用现有 `prepare_tushare_*_batch.py` 与 `run_tushare_*_batch.py` 的同一类合同：先只读计划，再明确 manifest/分片及 SHA、配置 SHA、任务集合、请求数和时间上界；只在 Mac 唯一归档写入环境执行。不得把旧 docs 中的日期、任务 ID、release 或临时 runner 当本轮授权。

RRG 的可复用入口包括 `audit_tushare_rrg_etf_window.py`（固定版缺口）、`prepare_tushare_rrg_acquisition_batch.py`（离线生成分片）和 `import_tushare_rrg_acquisition_shard.py`（默认只计划，显式写入）；精准执行用 `run_tushare_rrg_acquisition_batch.py`，饱和父任务的后代用 `run_tushare_rrg_descendant_batch.py`。后代执行须从已校验父集合推导完整当前图，不能把 split_pending 父任务当 pending 再跑。各工具参数以实际 CLI 定义为准，不另启第二个采集入口。

采集后分别验原文/观察/Parquet 闭包、固定发布和目标 reader，再用 `verify_tushare_rrg_coordinates.py`、`prepare_tushare_rrg_case_inputs.py`、`prepare_tushare_rrg_pit_etf_bridge.py` 或 `prepare_tushare_rrg_stock_point.py` 生成对应研究输入。工具读取成功或坐标可计算不解除行业历史成员、ETF 历史池、价格/复权/真实成交条件及公告 known_at 缺口；研究准入须另按课题合同验收。
