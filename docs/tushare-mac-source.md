# Tushare 归档、研究供数与恢复

用途：维护 Mac 唯一归档写入者及现有云端研究缓存。本文说明代码合同和操作前置条件，不证明当前服务已启动、配置已应用或历史已采齐。市场编排与状态入口见[本地市场数据源](local-market-source.md)；附件合同见[原文与附件生命周期](tushare-document-storage.md)。

## 归档与自动范围

- 完整归档默认根为 `~/Library/Application Support/QuantMind/tushare`，独立于 `.local-dev`。`ARCHIVE_AUTHORITY.json`、节点身份和 `ENABLED` 共同约束写入；旧源的 `ARCHIVE_RELOCATED.json` 是持久停写栅栏，不得删除以恢复云端采集。
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
2. 在 Mac 主工作树执行 `python3 scripts/install_tushare_archive.py` 准备持久客户端。默认只准备运行时，不启动采集；需要 uv 和已有依赖获取条件。
3. 私有凭据只放在 `tushare-client/config/archive.env`，权限 0600，使用 `TUSHARE_TOKEN`；不写入命令参数、发布清单、报告或同步载荷。
4. 归档所有权、完整性和私有配置已核实后，才执行 `python3 scripts/install_tushare_archive.py --activate --root /absolute/archive` 安装 `com.quantmind.tushare-archive`。已有 worker 时安装器拒绝覆盖。恢复 ENABLED 属于显式恢复采集，不是只读验证。

原生 worker 保留 300 GiB 余量，500 GiB 以下发迁移提醒；不足时停止新采集而非删除唯一归档。轮次默认 120 秒，可配置 105–3600 秒；模板覆盖为 300 秒。实际发布间隔以运行配置为准。WAL + FULL 的耐久边界不得用降低 synchronous 换吞吐；迁 NAS 前停唯一写入者并验证文件系统锁及 SQLite WAL 语义，必要时在私有环境显式使用 `QM_TUSHARE_SQLITE_JOURNAL_MODE=DELETE`。

## 频控、权限与失败恢复

账户 gate、API gate、供应商已观察冷却、每日总量都必须保留。`rate_policy=legacy` 是默认；显式 `tiered_v1` 仍受更严格合同/配置/已观察限制约束，未知 API 不因其他接口成功而提档。提高并发、规划预算或发布周期不增加供应商配额。

`cyq_perf` 的 `daily-quota.sqlite` 在请求前耐久预留，失败/超时不返还；损坏或时间回退失败关闭。它只覆盖同 root、同入口调用，不能代表全账户对账，删除账本不能恢复当天额度。权限积分和独立权益有到期边界，使用 `pipeline-status.json.rate_policy.entitlement`，不把购买记录或积分门槛当实际权限证明。

发生失败先保存状态和错误阶段，核对磁盘、authority、凭据权限、锁所有者与实际响应；不要用重置队列、抹除 permission gap 或扩大预算掩盖问题。低频权限复查只有真实成功才恢复对应 `api_name + src`，不外推到其他接口或来源。SQLite 状态缺失/损坏应保留原件并从一致备份制定恢复方案，不从固定研究子集重造全量采集检查点。

## 私有研究供数

```sh
# Mac：仅回环监听，由 SSH 反向转发到现有消费者
python3 scripts/tushare_research_cache.py serve --root /absolute/archive
# 消费节点：独立缓存根，来源只允许 SSH 回环隧道
python3 scripts/tushare_research_cache.py pull --root /absolute/research-cache \
  --source http://127.0.0.1:18765 --budget-gib 50 --reserve-gib 100
```

供数只导出审核 API 的 Parquet、所引用 observation 和 schema，不导出原始附件、SQLite、配置或密钥。默认 API 集合在脚本 `DEFAULT_APIS`；如需扩大，显式核对实际 `--apis`，不能把归档白名单等同于供数白名单。

所有文件校验后才原子切换缓存 CURRENT；离线、损坏或预算不足保留旧版。`cache-transfer-status.json` 是传输进度，`cache-status.json` 才是已切换结果。`source_release_id` 是实际源版本，`latest_source_release_id` 是已知最新版本；`source_lagged=true` 是未追平，任务成功不消除该缺口。旧缓存不自动删除，以免损坏运行中固定输入。

现有 `deploy/tushare-research-cache.service` 使用 50 GiB 缓存预算、100 GiB 余量；timer 在上次结束 15 分钟后再拉。脚本默认预算是 100 GiB，两者不同。只在消费者仍需此服务时维护 timer，不因远端开发退役而推断其数据服务已迁走。

应用 `QM_TUSHARE_READ_STORE` 只允许 `archive` 或 `research-cache`；切换先核对固定版实际查询，再在服务窗口重建容器加载环境。Mac 只读归档挂载由 `QM_LOCAL_TUSHARE_ROOT` 指定，改变后在无活动任务窗口运行 `bash scripts/local-dev.sh recreate-backend`，核对实际挂载源及只读标志；重启不改变挂载，固定研究作业另验输入。

## 归档搬迁与旧源回收

`scripts/tushare_archive_migrate.py` 处理归档迁移，不是开发 handoff。需要再次搬迁时保留唯一写入者、一致 checkpoint、完整文件 SHA 校验和原子所有权交接；先阅读其 action 前置条件，不复用历史接管收据作为新节点证明。

`precopy` 不复制活动 SQLite、不切 CURRENT；`checkpoint` 要求 ENABLED 已关闭并取得写锁；`sync-frozen` 补传冻结清单；`install-checkpoint` 不覆盖不同库或 WAL；`verify`/`finalize` 分别完成文件验收与旧源停写栅栏后才授予新所有权。任一步失败保留两端证据，不启动第二写入者。

`verify-preserved` 和 `prune-relocated` 的旧合同要求原件逐文件保留，后者默认只预检、`--apply` 才删除。附件已有退役后，不得把保留文本或退役收据冒充旧 PDF 的 PRESERVED 证明；需要兼容退役的新迁移基线，旧全量镜像也会明确拒绝退役归档。不要重启旧镜像补回有意退役的 PDF。业务库、冻结研究输入、快照和未知文件不因归档搬迁而获得删除授权。

## 显式课题补采与固定版审计

普通 `tick` 会做全局规划/发现，不能保证下一个请求属于指定批次；提高 priority 也不证明精确范围。手动补采使用现有 `prepare_tushare_*_batch.py` 与 `run_tushare_*_batch.py` 的同一类合同：先只读计划，再明确 manifest/分片及 SHA、配置 SHA、任务集合、请求数和时间上界；只在权威节点执行。不得把旧 docs 中的日期、任务 ID、release 或临时 runner 当本轮授权。

RRG 的可复用入口包括 `audit_tushare_rrg_etf_window.py`（固定版缺口）、`prepare_tushare_rrg_acquisition_batch.py`（离线生成分片）和 `import_tushare_rrg_acquisition_shard.py`（默认只计划，显式写入）；精准执行用 `run_tushare_rrg_acquisition_batch.py`，饱和父任务的后代用 `run_tushare_rrg_descendant_batch.py`。后代执行须从已校验父集合推导完整当前图，不能把 split_pending 父任务当 pending 再跑。各工具参数以实际 CLI 定义为准，不重新启用云端采集作为便捷入口。

采集后分别验原文/观察/Parquet 闭包、固定发布和目标 reader，再用 `verify_tushare_rrg_coordinates.py`、`prepare_tushare_rrg_case_inputs.py`、`prepare_tushare_rrg_pit_etf_bridge.py` 或 `prepare_tushare_rrg_stock_point.py` 生成对应研究输入。工具读取成功或坐标可计算不解除行业历史成员、ETF 历史池、价格/复权/真实成交条件及公告 known_at 缺口；研究准入须另按课题合同验收。
