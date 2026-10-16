# ashare-lab 撮合桥接

用途：维护分数信号到 ashare-lab 的次日开盘撮合合同，与标准 Qlib 路径区分时点、费用及适用条件。实现见 `bridge.py`；不修改外部市场面板。

## 环境前提

- `ASHARE_LAB_SRC`：默认仓库内 `vendor/ashare-lab/src`，不再依赖旧 ashare worktree。
- `ASHARE_LAB_PANEL`：默认 `vendor/ashare-lab/data/panel`，链接到本仓库归档的 main 原始固定面板，不跟随 CURRENT。
- `ashare_lab_available()` 同时检查源码导入与 `daily.parquet/calendar.parquet/stocks.parquet/index_members.parquet/index_daily.parquet`，不能只看目录存在。
- 部署挂载由现有 `local-primary` 链设置；桥接本身不启动服务、不采集行情，其他节点的依赖及数据必须实际确认。

## 输入与撮合

`run_signal_backtest(signals, start, end, config=BridgeConfig(), data=None, panel_dir=None)`：

- 输入为 `Series` 或含 `score` 列的 `DataFrame`，双层索引 `(datetime, instrument)`；转换为 `(date, code)` 后缀代码，拒绝重复索引并丢弃空分数。
- 未提供 `data` 时，从面板读取 `start` 前 450 个自然日至 `end`，用于上市天数和成交额筛选。
- 信号日 T 收盘后选股，T+1 开盘撮合；在 `eligible` 成员中按分数取 TopK 等权，同分按代码稳定排序；无信号日不调仓。
- 默认 `BridgeConfig`：资金 1000 万、TopK 50、中证800、上市 250 天、最低成交额 5000 万、整手 100 股；佣金 0.025%、过户费 0.001%、滑点 0.1%；印花税按 2023-08-28 前 0.1%、之后 0.05% 分段。实际请求可覆盖传入的配置项，不能把这些默认值套到标准 Qlib 路径。
- 失败返回 `BridgeResult(success=False, error_message=...)`，调用方必须检查，不能用空净值冒充成功。

## 结果口径

`BridgeResult` 包含 `nav/trades/annual_return/sharpe_ratio/max_drawdown/total_return/portfolio_dict`。前三项年化/夏普/回撤取 ashare-lab 指标（无风险利率 0），总收益为末日 NAV / 初始资金 − 1。

`portfolio_dict.report` 供 `RiskAnalyzer` 使用：`account=nav`、`cash`、`value=nav-cash`；`cost_amount` 是当日费用元额，`cost` 除以前日净值，`turnover` 为当日成交额/前日净值，`return` 是费前收益（减 `cost` 得净收益）；首日以前置初始资金作为分母。`execution_model=ashare_lab_next_open_lot` 用于识别执行语义。

## 接入回测服务

`backend/services/engine/qlib_app/services/backtest_service_runtime.py` 只对可映射的 `csi300/csi500/csi800/csi1000` 股票池且桥接依赖可用时允许该路径；自定义池、文件池和 `all` 不按指数猜测。调仓间隔先读策略 `kwargs.rebalance_days`，再读请求参数，缺省 1。

页面“A股真实撮合”开关发送 `use_vectorized`。条件不满足走标准 Qlib；已进入桥接路径但运行失败则报告错误，不静默换引擎。日志与结果必须能区分两种执行模型。

回归入口：`backend/services/tests/test_ashare_lab_bridge.py`、`test_ashare_lab_runtime_gate.py`；需要外部面板的用例须单独准备依赖，不能由合成单元用例推断真实撮合已验收。

## 冻结源码、成果和输入保留

`output/ashare-takeover/` 保留 main、a-line/events、research/b-line、
paper/forward、paper/s1-etf、research/expansion、research/ideas、
research/ideas-cb、research/ideas-cta 九棵原树，以及既有 QDII/crypto 报告。
包括 tracked/untracked/ignored 的图、CSV、日志、缓存、data/extra 和原账本；
旧树/旧备份未修改。归档根身份为
`c76d30551f39214afc5a31e7e251bb5d5ba968ea5a7373d8ed3fe7cdfe0990cf`，
26,650 个去重对象、6,533,360,491 字节，不含视图重复/Git bundle/索引。

`identity.json` 固定各原路径、branch/HEAD/status/refs 和清单哈希；
`manifests/*.jsonl`/`manifest.sqlite` 保存每文件路径、SHA、大小、git_state、
权限/mtime、原链接文本及实体路径。`trees/` 为只读视图，实体只在本归档内共享 inode，
不与旧树共享；Git all-refs.bundle、working/index.patch 另存原代码状态。
`vendor/ashare-lab/frozen-source.json` 是原文件选择及原 SHA/commit 证据，
基础 assembly ID `c666b6f9f95630e37b788ac83604f06920d46d04bf554aacb9dbdb434a01087e`
不能冒充纸盘扩展后实际 runtime hash；后者由登记及账本 identity 单独固定。
`frozen-data.json` 固定各树 data 身份；ignored 归档不是可删除的构建垃圾。

### 固定结果对账

`python3 -B scripts/ashare_parity.py --groups 05 B2 B3 B5` 只跑原冻结配置，
比较原值、summary/annual/NAV/exposure/trades，rtol=atol=1e-12，不做 grid/choose/调参。
05 参考 main；B2/B3/B5 参考 B-line 的原未跟踪 NAV/成交/因子，先核主树同名原件 SHA，
B3 不重算因子。新增 impact/cut 字段须证明中性，不能掩盖原列差异。
每次只写新 UTC 目录，失败证据不覆盖。现有真实通过证据为：

- `output/ashare-parity/20261016T185320563114Z/parity.json`：05 的 is/oos/full 三项；
  该轮不是十四项全部通过。
- `output/ashare-parity/20261016T190137688398Z/parity.json`：B2/B3/B5 十一项，
  包括 exposure 与 B5 逐笔成交；早期失败报告保留。

这证明冻结工程 parity，不授予策略或实盘资格。归档查询可用：
`sqlite3 output/ashare-takeover/manifest.sqlite "SELECT tree,commit_id,files,bytes,manifest_sha256 FROM trees;"`。
`scripts/ashare_preserve.py` 只允许新目标，拒绝覆写现有归档。

### 原生登记和唯一来源

`scripts/ashare_register_frozen.py --user-id <既有用户ID> --tenant-id default`
默认仅输出计划；`--apply --out <全新JSON>` 才由唯一 strategy_storage 登记。
固定八户、原研究边界、初始资金和权限合同见[后端纸盘契约](../../README.md#冻结-ashare-纸面观察)。
生命周期 DRAFT、is_verified=false、observation_only=true、trading_permission=false。
每项绑定含 strategy_id/frozen_source_id/runtime_code_sha256/strategy_code_sha256；
native async run、CLI 与 API 共用真实 owner/tenant 和精确版本校验，不复制资金或另建调度。

补源仅复用既有 Mac tushare-client Pipeline 的 authority/锁/额度/冷却，
有限 SSE 日历、三个 ETF、转债缺日和原 45 商品品种；不启全局历史采集。
`ashare_native_source.py tick` 使用 Asia/Shanghai/真实 SSE 日历，每次最多七个闭市日，
受管 `maintenance/ashare-native-source/state.json` 续自己的稳定任务，不派发外部 pending。
每批最多 128 请求/90 秒窗口；busy 延期、不停原 worker、不改 ENABLED。
原生 full/research 发布仍按既有 86400 秒节奏，不能每十五分钟少量新行强扫全归档。
native source 已提交但 export 未封存时先续纯 export；异常保留阶段，不提前推进 cursor。

派生内容键包含相关已验证 source refs、cutoff/replay、原归档身份及规范化代码 SHA，
只发布 `ashare-input-supplements/assets-<data_identity>/`。命中先核全部 manifest/payload，
无派生/无 staging；UTC 操作目录仅审计，不进入公开数据身份。
唯一 CURRENT 四字段 schema_version=1/data_identity/bundle_path/bundle_sha256；
缺失/损坏/旧 schema pending，不扫描旧 epoch、不恢复已删除 seed-operation 自动路径。
五资产由 source QA 逐户准入，供应商请求成功不等于输入或策略通过。

商品 raw multiplier 为 NULL 可以合法，按真实物理单位产生 normalized_multiplier，
保留公式、原字段和 source_object_sha256；未知实际使用闭包阻断，不拿无关历史缺值
永久阻断，也不用 CFFEX/同品种猜值。真实合并日历来自已核验 committed refs，
逐日期核 is_open/非空 pretrade_date 一致，复用 data.build._cache_api 合并而非造 weekday。
当前合并版本 `3d722ef5123e682a43fe12b201f2238adfa929b20961105dd72cdbc4b6d6b24c`
含 361 refs/35,657 行，去重 13,162 个 SSE 日期 1990-12-19..2026-12-31、零冲突。
同根 `derived/ashare-input-supplements/calendars/` 的 merged Parquet 与 source closure
必须随归档部署，不能只带 Q4 片段。最终复用证据
`20261016T205306494927Z-merged-calendar-reuse/reuse-proof.json`：
连续两次 0 HTTP/无派生/无 staging，五项公开身份、CURRENT 和日历/闭包相同。
旧单片日历 QA green 不冒充最终 runtime 成功；股票 usable 10/15、资产输入 10/16。

原生持续命令复用 `tushare-client/.venv/bin/python`，显式
`--root <受管归档> --client <原持久客户端> --artifact-root <Main/output>`。
`render-launchd --out <新plist>` 仅渲染 `com.quantmind.ashare-native-source`，
部署负责人从最终 Main 代码安装至持久 Library 客户端并 bootstrap/读取首跑证据；
候选模板、QA green 和静态构建都不算实际入库/八户日更/API/页面通过。
