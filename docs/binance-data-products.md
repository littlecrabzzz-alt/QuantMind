# Binance 数据产品边界

用途：在采集、发布和研究准入前区分加密现货、代币化证券、美股证券与股票永续，防止同名行情混用。下述为仓库已审核产品合同，不代表账户或所在地可交易，也不证明当前上游可用；增量和固定版本操作见 [Binance 运维](binance-data-operations.md)。

## 审核范围与研究准入

| 产品 | 仓库入口与审核范围 | 不可混同的边界 |
| --- | --- | --- |
| `crypto_spot` | `blockchain_sync.SPOT_PRODUCTS`：BTC、ETH、BNB、SOL、XRP、DOGE、ADA、LINK、AVAX、LTC 的 USDT 交易对 | 默认日更仍只有 BTCUSDT/ETHUSDT；登记扩展不自动改变默认池 |
| `tokenized_equity_spot` | AAPLBUSDT、AMZNBUSDT、NVDABUSDT、TSLABUSDT 独立目录 | bStocks 不赋予底层股票直接所有权；OHLCV 不是标的证券复权价 |
| 美股 Stocks Trading | Stocks SAPI 行情要求 API key；未接入此采集发布链路 | 不能用股票代币或永续代替证券历史行情 |
| `equity_perpetual` | 独立 `equity_perpetual_archive`，当前内置 CXMTUSDT/UNITREEUSDT 归档登记 | A 股相关的 USDT 永续不是沪深现货，不进入现有加密现货研究入口 |

审核登记不等于已采齐、已发布、持续更新或研究就绪。股票永续 manifest 保持 `research_ready=false`；当前研究适配仅接受 `crypto_spot`。其他 symbol 必须先核对产品、上市时间、底层证券/市场、计价及结算资产；不能凭 `USDT` 后缀或公司名称分类。

## 时间、字段与来源

- 来源为官方公共 REST 或官方日/月归档及 CHECKSUM；不调用账户、签名或订单。401/403/451 等限制不通过换域名或其他身份绕过。
- 现货官方归档自 2025-01-01 使用微秒，REST 与衍生品归档可能为毫秒，表头也不同。解析必须识别时间单位/表头，统一 aware UTC，保存原始响应与哈希，不能直接按整数大小当交易日。
- 自然键为 `(symbol, open_time)`，只接受来源 `close_time` 早于截止时间的已收盘日线。`available_at` 是 bar 结束理论下界，不是系统当年已经观察到的证明；实际 `collected_at` 单独保存。
- `amount` 使用原生 quote_volume，价格/成交额按该产品 USDT 口径，不用收盘价乘 volume 估算，不替代底层证券交易所原币种价。
- 保留全部来源 OHLC、基础/计价量额、成交笔数、主动买入量额、来源版本与产品映射。股票永续上市首日可是不完整交易时段，不能自动当整日可交易样本。

## 研究前还需核对

bStocks 需公司行动、转换倍数与底层证券关系；永续需合约生命周期、标记价、指数价、结算及资金费，包含股息相关的 `Special` 资金费。现有归档只有日线，不能据此声称这些数据已补齐。

原始文件 CHECKSUM 通过只证明来源文件完整；固定发布、接收成功、Qlib/H5 派生和研究实际消费分别验收。`history_complete` 限于当前公共接口给出的所选 symbol 日线覆盖，不是 PIT、公司行动正确、策略有效或实盘准入。

## 产品核实来源

- [官方 Market Data Only](https://github.com/binance/binance-spot-api-docs/blob/master/faqs/market_data_only.md)：公共现货行情范围。
- [官方历史数据说明](https://github.com/binance/binance-public-data)：归档格式、CHECKSUM 和时间单位。
- [Stocks 行情文档](https://developers.binance.com/en/docs/catalog/advanced-trading-stocks-trading/api/rest-api/market-data)与[上线公告](https://www.binance.com/en/support/announcement/detail/95d746cb2b5e4d179c50d0026dd7dfbe)：证券交易与 bStocks 转换不是同一种产品。
- [bStocks FAQ](https://www.binance.com/zh-CN/support/faq/detail/f0c03cd6509a4085b4cce1636f16be38)：代币化证券所有权边界。
- [CXMT/NET 上线公告](https://www.binance.com/en-NG/support/announcement/detail/0872245db74c4daaabd4f11984ba52c1)与[BYD 公告](https://www.binance.com/zh-CN/support/announcement/detail/89a035c3ee0e4b7782bf0089323d8e78)：底层市场及 USDT 永续含义；BYD 标的是 H 股，不能按公司名归为 A 股。
- [USDⓈ-M 行情文档](https://developers.binance.com/en/docs/catalog/core-trading-derivatives-trading-usd-s-m-futures/api/rest-api/market-data)：合约元数据与资金费。

产品变化时重新核实官方资料及实际接口；保留失败边界，不能把历史匿名探测成功或某次 451 结果写成永久能力判断。
