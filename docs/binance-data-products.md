# 币安数据产品与接入范围

核实日期：2026-09-26。币安的加密现货、美股交易、代币化证券与股票永续是不同产品；同名标的不能直接合并价格、成交量或研究样本。

## 首期范围与产品分类

首期以 BTCUSDT、ETHUSDT 的 UTC 现货日线完成四步：历史补采、时间与字段规范、质量检查与增量更新、固定版本的研究入口消费验证。bStocks 使用独立数据集，AAPLBUSDT 的完整历史另行采集发布。下述股票永续归档只作为来源与格式样本，尚未接通合约研究。

后续同日的 [批量补录记录](binance-data-batch-20260926.md) 将现货扩至十币、bStocks 扩至四项，并将 CXMT/UNITREE 官方日线归档保存为独立 `equity_perpetual` 版本。以下初期样本证据保留；批次记录给出扩充后的覆盖与缺口，股票永续仍未接通合约研究。

| 产品 | 代表 symbol / 标的 | 行情来源与限制 | 本次数据边界 |
| --- | --- | --- | --- |
| 加密现货 | BTCUSDT、ETHUSDT | 无 key 的现货公共 REST 与日/月归档 | `crypto_spot` 首期研究池 |
| 美股 Stocks Trading | AAPL、TSLA 等美股及 ETF | `/sapi/v1/equity/market/exchangeInfo`、`tokenized-assets`、`quote` 均要求 API key；现行行情文档未列历史 K 线端点 | 未访问账户或 SAPI；不使用代币/永续行情冒充美股现货 |
| bStocks 代币化证券 | AAPLBUSDT / AAPL | 已实测公开现货 REST 与归档可读；代币化证券不等于直接持有标的股票 | 独立 dataset、独立发布与消费验收，不进入 `crypto_spot` |
| TradFi 股票永续 | CXMTUSDT / 688825.SH；NETUSDT / NYSE: NET；BYDUSDT / HKEX:1211 | USDⓈ-M 行情及公开归档；本机 `fapi` 返回 451 | CXMT 历史归档样本；A 股、美股、港股永续均不进入 `crypto_spot` 或传统股票现货池 |

币安 2026-08-17 的[官方公告](https://www.binance.com/en-NG/support/announcement/detail/0872245db74c4daaabd4f11984ba52c1)明确：CXMTUSDT 于 2026-08-18 05:00 UTC 上线，标的长鑫科技（上海证券交易所 688825），采用 USDT/CNH 汇率，USDT 计价结算，24/7 交易。因此 A 股相关产品已经存在，但该合约不是沪深现货。同一公告列出美股 NETUSDT；[BYD 上线公告](https://www.binance.com/zh-CN/support/announcement/detail/89a035c3ee0e4b7782bf0089323d8e78)明确其标的是比亚迪 H 股，不能按公司名称误归 A 股。

[Stocks API 上线公告](https://www.binance.com/en/support/announcement/detail/95d746cb2b5e4d179c50d0026dd7dfbe)说明美股及 ETF 直接交易与 bStocks 转换分别存在；证券订单由 Nest Trading 路由至 Alpaca 执行、清算和托管。[bStocks FAQ](https://www.binance.com/zh-CN/support/faq/detail/f0c03cd6509a4085b4cce1636f16be38)说明代币化证券不赋予标的股票直接所有权。产品存在与行情可读不代表用户所在地或账户可交易。

## 匿名接口实测

所有请求使用系统 `/usr/bin/curl`，保留 TLS 校验，无 API key、签名或账户调用。以下时间均为 UTC。

| 接口 / 对象 | 实测时间 | 结果 |
| --- | --- | --- |
| `data-api.binance.vision/api/v3/exchangeInfo?symbol=AAPLBUSDT` | 2026-09-26 02:59:04 | HTTP 200，`TRADING`，base=`AAPLB`、quote=`USDT` |
| 同域名 `/api/v3/klines?symbol=AAPLBUSDT&interval=1d&limit=3` | 2026-09-26 02:59:05 | HTTP 200；9/24、9/25 已收盘，9/26 未收盘，消费样本过滤后保留 2 根 |
| AAPLBUSDT 2026-08 现货日线 ZIP 与官方 CHECKSUM | 2026-09-26 02:59；精确请求时间见 JSON | 两者 HTTP 200，SHA-256 一致，31 根，8/1–8/31 |
| CXMTUSDT 2026-08 USDⓈ-M 日线 ZIP 与官方 CHECKSUM | 2026-09-26 02:59；精确请求时间见 JSON | 两者 HTTP 200，SHA-256 一致，14 根，8/18–8/31 |
| `fapi.binance.com/fapi/v1/exchangeInfo` | 2026-09-26；早先探测只保留日期 | HTTP 451，地区限制；之后未重试或切换域名绕过 |

公共现货接口的免认证范围见[官方 Market Data Only 文档](https://github.com/binance/binance-spot-api-docs/blob/master/faqs/market_data_only.md)。Stocks SAPI 的 API key 要求与字段见[官方 Stocks 行情文档](https://developers.binance.com/en/docs/catalog/advanced-trading-stocks-trading/api/rest-api/market-data)；本次没有请求该接口。`fapi` 的 451 不影响分别记录公开归档的可读结果，但不能因此宣称合约实时更新已经贯通。

## 保存的原始证据与时间口径

证据仅保存在本机主工作树 `.local-dev/binance-product-evidence/`，共两个 ZIP、两个官方 `.CHECKSUM` 和 `summary.json`；不作为研究发布目录。JSON 记录 URL、请求时间、HTTP 状态、哈希、行数、字段单位及未收盘过滤结果。

| 原始文件 | SHA-256 | 时间单位 / 表头 |
| --- | --- | --- |
| `AAPLBUSDT-1d-2026-08.zip` | `d525c5c982b643975aa8161b6a8fc3b769bce5facb45d65305452301fc5813bb` | 微秒，无表头 |
| `CXMTUSDT-1d-2026-08.zip` | `0e8b377fc6e959d7c5317f98bda82c10d5d079c992ec37fe458e65a749ecc766` | 毫秒，有表头 |

两份归档均保留 12 个来源字段：开盘时间、OHLC、基础资产成交量、收盘时间、计价资产成交额、成交笔数、主动买入基础资产量、主动买入计价资产额及来源保留字段。价格/成交额使用该交易对的 USDT 口径，不能替代标的证券交易所的原币种价格。CXMT 上市首根日线标记在 UTC 零点，其实际交易从 05:00 开始，属于上市首日的不完整交易时段。

币安[历史数据说明](https://github.com/binance/binance-public-data)明确现货归档自 2025-01-01 使用微秒；本次现货 REST 返回仍为毫秒。解析应识别单位与表头，统一为 aware UTC，保留原始文件。研究仅接受来源 `close_time` 早于取数截止时刻的已收盘 bar；源收盘时间为区间末尾，标准化 `available_at` 应不早于下一日 UTC 零点，并与实际 `observed_at` 分开记录。历史回填的采集时间不能伪装为当时已观测到的发布时间。

## 研究准入边界

- 每份数据保留交易场所、产品类型、底层市场/证券、计价与结算资产、来源版本；未知资产类型不可默认归为加密现货。
- bStocks 的公司行动与转换倍数单独处理；仅有 OHLCV 不代表已取得标的股票复权价格。
- 股票永续还需合约元数据、标记价、指数价、资金费和公司行动。官方[期货行情文档](https://developers.binance.com/en/docs/catalog/core-trading-derivatives-trading-usd-s-m-futures/api/rest-api/market-data)提供 `contractType`、`underlyingType`、`underlyingSubType` 等字段，并在资金费历史中区分 `Regular` 与股息相关的 `Special`；不能把后者丢弃。
- 原始归档可读及 CHECKSUM 通过，只证明来源样本完整。是否已发布、云端可读、被研究消费，必须分别用对应 release 与实际读取证据验收。本文件不赋予合约研究或实盘执行准入。
