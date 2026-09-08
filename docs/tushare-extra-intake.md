# 期货、财务研究补充接入

本批在既有不可变原文、观察、Parquet、固定 release 查询链路上增加 13 个接口。合同来源链接、字段、输入范围及未证明的历史下界保存在 `backend/shared/tushare_futures_extra_contracts.py` 和 `tushare_research_extra_contracts.py`。共 144 个文档字段；返回的额外字段也原样保留。账号权限以真实观察为准。

| 数据 | 接口 | 关键口径 |
|---|---|---|
| 期货日历 | fut_trade_cal | 交易所独立；cal_date/pretrade_date，不用股票日历代替 |
| 期货复权日线 | fut_daily_adj | 连续合约代码从返回数据发现，不假定都带 L 后缀 |
| 期货周月线 | fut_weekly_monthly | freq、周期标签 trade_date 与计算截止 end_date 同时保留 |
| 期货持仓排名 | fut_holding | exchange/symbol/broker 联合身份；缺少多空某侧不填 0 |
| 南华期货指数 | fut_index_daily | .NH 为供应商指数命名空间，独立发现 |
| 期货周统计 | fut_weekly_detail | week 为供应商周编码，week_date 才是日期，不能推定 ISO 周 |
| 期货涨跌停及保证金 | ft_limit | 按交易日、合约与交易所保留 |
| 审计意见 | fina_audit | 公告日与报告期分开，审计机构和签字人原样保存 |
| 主营业务构成 | fina_mainbz | 请求 type=P/D/I 是数据身份的一部分，不能因响应相同而合并 |
| 财报披露日历 | disclosure_date | 报告期、预披露、实际披露与修订日期分开；未来日期合法 |
| 盈利预测 | report_rc | report_date 为报告日期，quarter 是预测期；不等同付费研报 PDF |
| 机构调研 | stk_surv | 输入 trade_date 与返回 surv_date；content 的原始类型不强制改写 |
| 券商月度荐股 | broker_recommend | month 为月份，没有文档未支持的逐股过滤参数 |

## 原文与离线身份

HTTP 429/401/500 等完整错误响应也脱敏留存并参与 SHA256 清单校验，包括 HTML 正文；未完整收到的流不标记为完整原文。HTTP 错误即使正文有 code=0，也不会进入行情或发现数据。离线读者保留其失败观察，data 为 null。

fina_mainbz 的 P/D/I 从不可变请求观察恢复。固定 release 必须包含观察文件并通过大小/SHA256核验；缺少 type 或身份冲突明确报缺口，不能猜测。旧 Parquet 可在读取时恢复，不重写旧数据；新数据同时保存原始行哈希和请求身份。采集时刻不代表历史可知时刻。

## 验收与后续

离线 237 项 Tushare 测试通过，其中本批覆盖全部字段、额外字段、P/D/I、日期轴、期货发现、固定 release 和错误正文。真实请求与 Mac 镜像的阶段结果追加到 `tushare-progress.md` 和共享协调记录，离线通过不能作为账号权限证明。

未知历史起点、单次条数上限、修订范围、非标准分页及发现列表完整性均保留独立规划缺口。期货持仓饱和后需要交易所/品种成对分片；不能套用单个股票参数。信用补充的 7 个纯合同已准备，但未因文件存在计为生产接入。
