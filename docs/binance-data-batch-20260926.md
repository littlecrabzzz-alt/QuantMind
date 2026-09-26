# 币安批量补录与验证 — 2026-09-26

本批为用户确认的常见币种、币安官方可核实的 A 股相关产品和少量美股产品。共 16 个标的、29,550 根唯一已收盘 UTC 日线，含原有 BTC/ETH/AAPLB 的重新核验；新增 13 个标的。股票相关行情保留真实产品类型，不合并进传统证券或加密现货研究池。

## 实际日线覆盖

| Symbol | 产品类型 | 首日 | 末日 | 行数 |
| --- | --- | --- | --- | ---: |
| ADAUSDT | crypto_spot | 2018-04-17 | 2026-09-25 | 3,084 |
| AVAXUSDT | crypto_spot | 2020-09-22 | 2026-09-25 | 2,195 |
| BNBUSDT | crypto_spot | 2017-11-06 | 2026-09-25 | 3,246 |
| BTCUSDT | crypto_spot | 2017-08-17 | 2026-09-25 | 3,327 |
| DOGEUSDT | crypto_spot | 2019-07-05 | 2026-09-25 | 2,640 |
| ETHUSDT | crypto_spot | 2017-08-17 | 2026-09-25 | 3,327 |
| LINKUSDT | crypto_spot | 2019-01-16 | 2026-09-25 | 2,810 |
| LTCUSDT | crypto_spot | 2017-12-13 | 2026-09-25 | 3,209 |
| SOLUSDT | crypto_spot | 2020-08-11 | 2026-09-25 | 2,237 |
| XRPUSDT | crypto_spot | 2018-05-04 | 2026-09-25 | 3,067 |
| AAPLBUSDT | tokenized_equity_spot | 2026-07-29 | 2026-09-25 | 59 |
| AMZNBUSDT | tokenized_equity_spot | 2026-07-29 | 2026-09-25 | 59 |
| NVDABUSDT | tokenized_equity_spot | 2026-06-11 | 2026-09-25 | 107 |
| TSLABUSDT | tokenized_equity_spot | 2026-06-11 | 2026-09-25 | 107 |
| CXMTUSDT | equity_perpetual | 2026-08-18 | 2026-09-25 | 39 |
| UNITREEUSDT | equity_perpetual | 2026-08-19 | 2026-09-24 | 37 |

10 币合计 29,142 行；4 项 bStocks 合计 332 行；两项 A 股相关股票永续合计 76 行。UTC 2026-09-26 的未收盘日线不纳入。日线 bucket 完整不代表上市首日交易满 24 小时。

[长鑫科技 CXMTUSDT](https://www.binance.com/en/support/announcement/detail/0872245db74c4daaabd4f11984ba52c1) 的底层映射为 688825.SH，上线时间 2026-08-18 05:00 UTC；[宇树科技 UNITREEUSDT](https://www.binance.com/en/support/announcement/detail/3e662272597c44b7939f5db5c8c86d4f) 为 688836.SH，上线时间 2026-08-19 02:45 UTC。两项都是 USDT 计价结算的股票永续，不是沪深股票现货持仓。首日部分交易时段已逐行标记，价格未转换为人民币。

AAPLB/AMZNB 的底层映射为 AAPL/AMZN，[上线时间](https://www.binance.com/en/support/announcement/detail/fd3c0f17a7504eb5be1cb1911c6da0cd)为 2026-07-29 12:00 UTC；NVDAB/TSLAB 对应 NVDA/TSLA，[上线时间](https://www.binance.com/en/support/announcement/detail/5646e3f9ea6b4c989cb76aa18bd99245)为 2026-06-11 18:00 UTC。这些数据是 bStocks 行情，不是底层证券交易所的复权价格。BYD/ZHONGJI 的已核实产品对应 H 股，MOONSHOT 为 Pre-IPO，本批不将其归为已上市 A 股。

## 宇树缺口及发布边界

请求至不含 2026-09-26 时，UNITREE 的 09-25 官方日包返回 404，产生 `equity-perpetual-70c1946c5fb152b69220d8f3` partial 版本：37 行，缺 1 日，不切换 CURRENT。随后显式改为不含 09-25 的截止日，发布完整前缀 `equity-perpetual-55dd930575654680ba9963ec`；旧 partial、缺包 URL 与原始归档全部保留。

股票永续使用官方公开归档与 CHECKSUM，未重试受限 Futures API 或更换访问路径。两项 manifest 均为 `research_ready=false`；尚缺资金费、标记价、指数价、公司行动和执行规则适配。所有产品的 `point_in_time_verified=false`：采集于今天的历史回填不能证明历史实际可见时间。

## 验证与发现

- 旧云端 BTC/ETH 和 AAPLB 文件哈希、原始经济值、派生绑定检查通过。本机旧 BTC/ETH 仍为固定旧版，存在最高 2 ULP 的旧解析差异；旧版保留，未伪称两端版本相同。
- 新批现货共 3,440 个发布 payload、64 个原始对象的哈希通过，265,266 个经济数值逐值等于原始十进制转 Python float。14 个标的无缺日、重复或未闭合行。
- 永续的两份完整版本及一份 partial 证据共 113 行、1,130 个经济值逐值通过；125 个 payload、304 个 raw 文件 SHA 和 76 次官方 ZIP 校验通过。
- 扩池独立验收发现旧 Qlib 构建器把所有标的起点写成全池日历首日。原始行情、两份 H5 与 70 个 Qlib 数值文件均正确，但标的生命周期错误。失败报告保留为 `derived-value-audit.json`；候选修复仅按 CRYPTO 每个标的的已验证首尾覆盖生成 instruments，并验证上市前日期不会选入后上市币种。

完整证据在主工作树 `output/binance-batch-20260926/`，包含产品来源、旧版审计、新批原始值审计、永续可复跑审计、测试与传输清单。最终云端读取和修复后派生验收结果附于本文件末尾。

## 使用与更新

本机数据根：`.local-dev/project/data/binance-batch-20260926/`。三个产品类别分别为 `crypto-spot`、`tokenized-equity`、`equity-perpetual/<symbol>`。各目录 CURRENT/manifest 指定固定版本，不能直接改 symbol 集合或替换旧研究输入。

新增现货沿用 `quantbc_daily_sync --symbols <完整列表> --data-dir <新根>`；股票代币另传 `--product-type tokenized_equity_spot`；股票永续使用 `equity_perpetual_archive --symbols <已审核symbol> --data-dir <独立根>`。具体流程见 [操作文档](binance-data-operations.md)。

本批是一次性补录；既有 BTC/ETH 每日 08:15 调度及旧输入保持原样，新池尚未设为默认币池或管理页数据根。未启动策略、回测、调度或交易。10 币的研究输入读取与股票产品的研究准入分别验收，不能用数据读取成功替代策略及成本验证。

## 最终发布与修复后验收

- 2026-09-26 07:28:56 UTC，新数据根已原子发布到云端 `/data/binance-batch-20260926`。传输包 SHA-256 `2743f9184a95e2f1760e039233780e7272a6d901f8d66a0b4afb913c498fd4dd`，4,010 个文件、69,209,439 字节逐个核验；原 `/data/quantbc` 和 `/data/binance-tokenized-equity` CURRENT 保持原样。
- 实现提交 `6c2c0d1ba1c443ddc9cf49e0aa7ac0afee20a49c`；相关采集/发布测试 42 项、含 Qlib/PyTables 的研究输入与路径测试 31 项，共 73 项通过、0 跳过。实际 Qlib universe 验证确认上市前不会纳入晚上市标的。其他市场行为保持原样。
- 本机修复后的完整派生复核通过；云端重新构建并独立复核也通过：两份 H5 各 29,142 行 × 7 字段逐值一致，70 个 Qlib 文件共 203,994 个 float32 数值和偏移一致，10 币起止范围正确，source_manifest 绑定同一固定版本。原始版本哈希未改变。
- 云端通过真实 RD 数据准备入口固定 task 输入，实际 Qlib 读取最近七日 70 个样本的收盘价、原生成交额和一日收益率；未运行策略研究或交易。验收 task 位于 `/data/maintenance/binance-batch-20260926/crypto-task`。
- 正式路径的 Hub 实读得到 29,142 行现货和 332 行 bStocks；CryptoAdapter 拒绝股票代币，QuantBC/CryptoAdapter 拒绝股票永续。正式归档三版本的 1,130 个经济数值及所有来源校验再次通过。
- 云端证据：`/data/maintenance/binance-batch-20260926/`。本机副本与逐份报告哈希见同名 JSON。源码/Git 已在实现提交完成双端对齐；CLI 实际加载和读数已验证。共享 API/worker 未重启，管理页仍指向旧池，不能将此批补录描述成页面扩池或新增自动日更。

这是一组选定标的的当前公共历史覆盖，未包含完整历史退市币池；股票相关产品还未通过股票/永续研究所需字段与执行模型验收。数据质量验收不构成策略有效性或实盘授权。
