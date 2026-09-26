# 币安数据采集、发布与研究输入

首期为 BTCUSDT、ETHUSDT 的加密现货 UTC 日线；AAPLBUSDT 单独归为美股代币化证券。产品依据与合约限制见 [产品核实](binance-data-products.md)。当前研究输入准入只开放 `crypto_spot`，不将代币、股票永续或底层证券行情混合。

2026-09-26 扩充批次采用独立根目录，范围与实际验收见 [批量补录记录](binance-data-batch-20260926.md)。默认 BTC/ETH 币池、现有调度和已有研究的固定版本不随登记表扩充而改变。

## 采集与增量

在项目根目录执行，明确指定本节点的数据目录。公开现货行情不需要账户或 API key。首次使用早于上市的开始日期；后续运行自动保留全部已发布历史，从最新已存日向前回看一周，重拉重叠区间。

```sh
python3 -m backend.scripts.quantbc_daily_sync \
  --symbols BTCUSDT,ETHUSDT --start-date 2010-01-01 \
  --data-dir /absolute/path/to/quantbc

python3 -m backend.scripts.quantbc_daily_sync \
  --symbols BTCUSDT,ETHUSDT --data-dir /absolute/path/to/quantbc

python3 -m backend.scripts.quantbc_daily_sync \
  --symbols AAPLBUSDT --start-date 2010-01-01 \
  --product-type tokenized_equity_spot \
  --data-dir /absolute/path/to/binance-tokenized-equity
```

`--end-date` 为不含当天的 UTC 日期，默认 UTC 今天。`--refresh-history` 会重新核验本目录已有的全部历史；常规增量不能发现七天以前才出现的上游修订。分钟线、估值、未审核 symbol 和不匹配的产品类型明确拒绝。

来源采用币安官方公开现货 REST，429/5xx 有限重试；4xx 停止，不换域名绕过地区限制。月归档下载同时校验官方 CHECKSUM，识别现货 2025 年以后的微秒时间。原始响应与采集元数据保存在 `raw/`，失败请求可按相同窗口恢复；新一轮采集使用新缓存，避免永久读旧响应。

## 发布合同

- 自然键为 `(symbol, open_time)`。检查 OHLC、非负成交量、原生成交额、时间单位、UTC 已收盘、首尾覆盖、连续性、重复及非有限值。
- `amount` 等于币安原生 `quote_volume`，不由收盘价乘成交量估算。保留成交笔数、主动买入量额、来源哈希及采集时间。
- `available_at` 是 bar 结束的理论下界；`collected_at` 是本次实际采集时间。manifest 明确 `point_in_time_verified=false`，历史回填不能证明当年当时已经收到该数据。`history_complete` 仅指当前公共接口可提供的这组 symbol 日线覆盖。
- `releases/<release_id>/` 保存日线、标的元数据、质量报告和文件 SHA-256；仅在整体检查通过后原子更新 `CURRENT.json`。失败保持旧指针，旧研究输入不随指针移动。
- 同样行情及元数据重复发布保持原版本；交易规则等元数据变化会生成新版本，即使行情行数和价格未变。无变化响应返回该固定版本的质量报告，本轮检查结果另存 `checked_quality`。
- 经济数值由原始十进制字符串统一转换为 Python binary64，manifest 记录 `numeric_semantics=python_float_binary64_from_source_decimal`。从旧解析口径升级时自动完整回采已有历史，成功后发布新版本；不能只更新尾部再将全部旧历史标为新口径。首次迁移的浮点末位变化属于解析归一化，需结合相同原始响应哈希判断，不能直接称为上游行情修订。
- 已核实 2018-02-08 的 BTC/ETH/BNB/LTC REST 收盘时间异常：仅在校验通过的月归档与 REST 全部经济数值一致时采用归档行，记录 `source_revision`、原始 REST 收盘时间及哈希。价格或量额不一致时阻止发布。

## 研究数据与真实验收

`--build-research` 在发布后构建 Qlib/H5；需要现有后端镜像中的 Qlib 与 PyTables。派生文件位于 `derived/<release_id>/`，不会写回不可变原始版本。每个 RD 任务复制固定 Qlib/H5，并携带 `source_manifest.json`；已有任务拒绝换用另一个 release。

加密现货 Qlib 的 `instruments/all.txt` 必须按每个标的的实际数据首尾日期写入；不能把全池日历首日当作所有币种的上市日。扩池验收同时核对文件数值、时间偏移和标的生命周期，并验证上市前日期不会选入该币。

```sh
python3 -m backend.scripts.quantbc_daily_sync \
  --data-dir /absolute/path/to/quantbc --build-research

python3 scripts/binance_data_acceptance.py \
  --data-dir /absolute/path/to/quantbc \
  --task-dir /absolute/path/to/acceptance/task \
  --report /absolute/path/to/acceptance/research-report.json
```

验收实际调用 QuantBCDataHub、CryptoAdapter、RD 的数据准备入口和 Qlib `D.features`，比较全部原始/H5 行数，并将最近七天的收盘价、原生成交额、一日收益率与原始 Parquet 比对；最后重新核验原始版本文件哈希。此脚本只做数据准备和读取，不运行模型训练、策略、回测或交易。

## 后续增加币种或股票

当前入口审核产品类型并固定每个目录的 symbol 集合，尚无页面一键扩池功能。新增标的需要一次明确的代码/配置变更：

1. 核实交易场所、产品类型、上市日、计价资产和底层证券映射，在 `backend/scripts/blockchain_sync.py` 的 `SPOT_PRODUCTS` 登记审核结果。不能仅因名字以 USDT 结尾就归为加密现货。
2. 扩大的币种池使用新数据根，明确传入完整 `--symbols` 列表并从上市起补采。当前 publisher 会拒绝在既有目录增删 symbol；不能直接修改旧 manifest 或 CURRENT 来绕过校验。
3. 新池完成质量、完整覆盖、成本字段及 Qlib/H5 消费验收后，才切换新任务的默认数据根和采集配置。现有 BC 调度采用代码中的默认 BTC/ETH 池；只在命令行采了新币不会自动改变日更池。
4. 已有研究继续读取原 release；新研究显式记录新币种池与新 release。资产数量扩展不等于策略逻辑、交易成本及回测执行模型已经适用。

股票代币沿用独立产品目录，进一步核验公司行动、转换倍数和底层证券关系；不能当作底层证券复权价。股票永续需独立合约适配，补充资金费、标记价、指数价、结算与合约生命周期。真正的 A股、美股证券优先使用现有 QuantDB/QuantUS 入口，分别保留本地交易日历、币种及复权合同。两类入口不能通过同名 ticker 直接合并。

已审核的股票永续可用独立归档入口保存日线。该入口只读取官方公开归档和 CHECKSUM，不调用 Futures API；每个合约使用独立根，避免一项归档延迟阻止其他合约发布：

```sh
python3 -m backend.scripts.equity_perpetual_archive \
  --symbols CXMTUSDT --start-date 2010-01-01 --end-date 2026-09-26 \
  --data-dir /absolute/path/to/equity-perpetual/CXMTUSDT
```

`--end-date` 仍为 UTC 不含端点。缺文件产生不可变 partial 版本和 `missing.json`，退出码为 2，保留旧 `CURRENT.json`；无旧版时不创建指针。补采已知完整前缀必须显式指定较早截止日，脚本不会自动缩短窗口。401/403/451 等限制立即终止，不自动更换入口。所有 ZIP、校验文件、采集时间、原生 USDT 量价和上市首日部分交易标记均保留。即使日线窗口完整，manifest 的 `research_ready` 仍为 false，当前加密现货研究入口拒绝该产品。

## 定时更新口径

BC 建议时间为北京时间 08:15，即 UTC 日线闭合后 15 分钟。既有调度每天补派一次；当天错过时刻可补派，但任务失败后当天不自动重试，需检查失败原因再手动执行。长停机后的增量按已存最后一日回补，不再被 `days` 的短窗口截断。要求构建研究数据时，BC 的 Qlib/H5 跳过或失败会将总体结果标记为 partial。

管理员 QuantBC 数据页独立于全局 crypto 研究开关；可保持 `ENABLE_CRYPTO=false`、`VITE_ENABLE_CRYPTO=false`。日更使用显式已验证 release 准备 Qlib/H5，不因数据构建把全局研究市场打开。

## 当前部署边界

2026-09-26 已将通过逐文件 SHA-256 校验的固定版本发布到云端 `data/quantbc` 和 `data/binance-tokenized-equity`。BTC/ETH 的 BC 调度已通过管理 API 保存为每天北京时间 08:15、`days=5`、`daily_forward` / `instrument_detail`、`with_qlib=true`，并已自然补派成功一次。当前管理页只展示这两项已实现的数据集。

云端是 BTC/ETH 日更的唯一写入者。AAPLB 仍为独立固定版本，未启用其自动采集或研究。Mac 沙盒 `.local-dev/project/data/` 下保留首次验收的固定版本；目前没有 BTC/ETH 云端新版本自动回传 Mac 的链路，也不通过 Syncthing 传数据。实际版本、任务和消费证据见 `coordination/binance-data/` 最新验收记录。

后端与前端全局 crypto 研究开关、实盘开关仍关闭。管理员可查看数据、保存调度和准备派生数据；这些操作不启动策略研究或交易。股票代币与股票永续不纳入 BTC/ETH 调度。历史回填仍不具备历史时点到达时间证明。
