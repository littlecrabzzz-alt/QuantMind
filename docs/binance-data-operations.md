# 币安数据采集、发布与研究输入

首期为 BTCUSDT、ETHUSDT 的加密现货 UTC 日线；AAPLBUSDT 单独归为美股代币化证券。产品依据与合约限制见 [产品核实](binance-data-products.md)。当前研究输入准入只开放 `crypto_spot`，不将代币、股票永续或底层证券行情混合。

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
- 2018-02-08 的 BTC/ETH REST 收盘时间异常：仅在校验通过的月归档与 REST 全部经济数值一致时采用归档行，记录 `source_revision`、原始 REST 收盘时间及哈希。价格或量额不一致时阻止发布。

## 研究数据与真实验收

`--build-research` 在发布后构建 Qlib/H5；需要现有后端镜像中的 Qlib 与 PyTables。派生文件位于 `derived/<release_id>/`，不会写回不可变原始版本。每个 RD 任务复制固定 Qlib/H5，并携带 `source_manifest.json`；已有任务拒绝换用另一个 release。

```sh
ENABLE_CRYPTO=true python3 -m backend.scripts.quantbc_daily_sync \
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

## 定时更新口径

BC 建议时间为北京时间 08:15，即 UTC 日线闭合后 15 分钟。既有调度每天补派一次；当天错过时刻可补派，但任务失败后当天不自动重试，需检查失败原因再手动执行。长停机后的增量按已存最后一日回补，不再被 `days` 的短窗口截断。要求构建研究数据时，BC 的 Qlib/H5 跳过或失败会将总体结果标记为 partial。

管理员 QuantBC 数据页独立于全局 crypto 研究开关；可保持 `ENABLE_CRYPTO=false`、`VITE_ENABLE_CRYPTO=false`。日更使用显式已验证 release 准备 Qlib/H5，不因数据构建把全局研究市场打开。

## 当前部署边界

本次真实数据保存于 Mac 沙盒的 `.local-dev/project/data/quantbc` 和 `.local-dev/project/data/binance-tokenized-equity`；不属于主工作树 `data/`，也不会经 Syncthing 传到云端。实际版本、测试结果和消费报告见 `coordination/binance-data/` 最新验收记录。

现有后台手动同步与市场调度入口已适配固定版本和研究数据构建。自动日更仍按前端保存的市场调度配置触发；安装代码不代表开启调度。若后续开启，日线应在 UTC 零点后留出上游发布余量，显示最新已闭合日期及失败状态。云端发布、界面市场开关及自动调度分别验收，不能由本地数据验收推断已经开启。
