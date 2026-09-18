# 结构化数据下一批接入契约

2026-09-09；实施分支 `codex/tushare-structured`。接续[总计划](tushare-integration-plan.md)和[任务书](tushare-integration-task.md)。本提交是纯函数契约/分片规划和目录台账；没有读取生产凭据、调用账号 API、写入云端数据或部署服务。账号积分不能替代逐接口实测。

新增 26 个采集端点，保留供应商全字段；`config/tushare-catalog.json` 的输出字段与契约 `extra_fields` 取并集。VIP 端点使用 `catalog_api` 找到普通端点字段表，`dataset_identity` 保留两者映射，不能把 VIP 当作没有字段的新 API。

| 组 | 接口 | 请求覆盖 |
|---|---|---|
| 股票主数据 | stock_basic、stock_company、namechange | 股票 L/D/P/G/UN × SSE/SZSE/BSE；公司按三交易所；历史名称按已发现全部股票保留完整快照 |
| 股票行情与制度 | daily、adj_factor、daily_basic、stk_limit、suspend_d、moneyflow | 配置历史起点至昨日逐日请求；资金流从官方 2010 起点开始；日历未验完整前不据其删除日期 |
| 财务 | income_vip、balancesheet_vip、cashflow_vip、fina_indicator_vip、forecast_vip、express_vip | 所有已结束季度；三大表显式请求 1–12 全部报表类型；近两年季度复查，其余稳定历史队列；已实测四个季度全市场接口的 offset/limit 分页 |
| 指数 | index_basic、index_daily | 枚举 MSCI/CSI/SSE/SZSE/CICC/SW/OTH；行情按已发现指数分年；SW 不由 index_daily 支持，保持显式待接入项 |
| 宏观 | cn_gdp、cn_cpi、cn_ppi、cn_m、cn_pmi、sf_month | 从配置起点请求季度/月度全序列，每日刷新可捕获既往修订；不伪造历史发布日期 |
| 利率 | shibor、shibor_quote、shibor_lpr | 分年历史和近期复查；含全部数值期限字段 |

官方资料逐页复查：股票主数据 [25](https://tushare.pro/document/2?doc_id=25)、[100](https://tushare.pro/document/2?doc_id=100)、[112](https://tushare.pro/document/2?doc_id=112)；行情 [27](https://tushare.pro/document/2?doc_id=27)、[28](https://tushare.pro/document/2?doc_id=28)、[32](https://tushare.pro/document/2?doc_id=32)、[183](https://tushare.pro/document/2?doc_id=183)、[214](https://tushare.pro/document/2?doc_id=214)、[170](https://tushare.pro/document/2?doc_id=170)；财务 [33](https://tushare.pro/document/2?doc_id=33)、[36](https://tushare.pro/document/2?doc_id=36)、[44](https://tushare.pro/document/2?doc_id=44)、[79](https://tushare.pro/document/2?doc_id=79)、[45](https://tushare.pro/document/2?doc_id=45)、[46](https://tushare.pro/document/2?doc_id=46)；指数 [94](https://tushare.pro/document/2?doc_id=94)、[95](https://tushare.pro/document/2?doc_id=95)；宏观 [227](https://tushare.pro/document/2?doc_id=227)、[228](https://tushare.pro/document/2?doc_id=228)、[245](https://tushare.pro/document/2?doc_id=245)、[242](https://tushare.pro/document/2?doc_id=242)、[325](https://tushare.pro/document/2?doc_id=325)；利率 [149](https://tushare.pro/document/2?doc_id=149)、[150](https://tushare.pro/document/2?doc_id=150)、[151](https://tushare.pro/document/2?doc_id=151)。社融对应目录 `sf_month` 的原始文档 URL 见台账。

接入现有采集器的接口：

```python
STRUCTURED_CONTRACTS[api_name]
iter_structured_jobs(config, today, identifiers=None)
structured_prerequisites(identifiers=None)
```

`config.history_start` 为 YYYYMMDD；默认全部 26 端点，`structured_apis` 仅供显式按批接入，不能用其缩小总目标。`today` 为上海当地 date。`identifiers.stocks/indexes` 必须来自已保存的全部状态/市场发现记录；这里只在供应商请求边界接受后缀代码，标准化与存储沿用主采集器前缀规则。股票/指数未发现时函数返回依赖缺口；基础资料仍照常入队。所有近期请求排在历史请求之前；输出为 `{api_name, params, priority, epoch}`，历史 priority=45、近期/基础=25。调用者持久化计划日期及游标，限制每次入队数量，不能每两分钟无界重建全历史。

数据正确性与待实际验证项：

- 2026-09-19 使用当前归档账号实测 `income_vip`、`balancesheet_vip`、`cashflow_vip`、`forecast_vip`：精确 `period=20260630` 的全市场请求支持 `limit=1000` 与连续 `offset`，各页无精确重复，重复请求首页稳定，并以不足 1000 行的末页闭合。完整链分别为 10604、11187、10555、1918 行；旧默认响应分别只有 9000、7000、6400、1916 行。证据只保留参数、计数、内容哈希与发布引用，不包含 Token 或原始业务行。
- 分页只应用于含精确 `period` 且不含 `ts_code` 的四个接口根任务；三大表仍显式请求 1–12 全部报表类型。连续 offset、字段 schema、终态和明确末页全部成立后，才把同范围、同字段的旧逐股票待办和旧饱和根任务标记为 `superseded`；已完成、失败、空结果、未闭合链和请求尝试均保留。`fina_indicator_vip`、`express_vip` 没有从这四项类推分页能力。
- VIP 行数上限仍没有独立文档证明，`row_cap_verified=false` 继续表示默认响应不等于供应商最大值。四个已验证根任务的近期季度优先级为 5、历史季度为 15；其他 VIP 接口保留原饱和告警和逐股票兜底。
- 三大表/预告/快报 start_date/end_date 是公告日期，fina_indicator 是报告期日期；`split_axis` 明确区别。初始季度请求不加公告日限制，以免遗漏公告日期为空的行；财务发布日期为空只影响 PIT 可用性，不应抛弃原始记录。近两年之外的迟到修订尚需低频全历史复查作业，当前代码不能证明覆盖此类修订。
- `namechange`、`adj_factor`、`suspend_d`、`index_daily` 等当前页缺少明确上限，`row_cap_verified=false` 保留不确定性。单日请求饱和不能仅按日期二分；需要标的扇出。`stk_limit` 含 A/B 股和基金，不能只拿 A 股集合来宣称完成其标的扇出。
- `index_daily` 不提供申万行业行情，SW 主数据照常保留，行情另走后续申万接口。当前股票和指数名单未证明穷尽供应商的历史标的；未知代码/停止维护端点继续列为缺口。
- 目录旧解析只提取字母/下划线开头字段，遗漏 Shibor 的 1w/2w/1m/3m/6m/9m/1y、报价 bid/ask 期限和 LPR 的 1y/5y，本契约通过 extra_fields 补齐。所有隐藏字段保留；金额单位/原始日期不在规划器转换。
- `requests_per_minute` 是保守操作上限，除 stock_basic 的官方 50 次/分钟外不宣称账号频控实测值；由主采集器统一账号限速、退避和自适应。
- 台账逐项保留全部 263 文档项，分类页也在分母。7 项已部分入库、9 文本及本批 26 项仅实施中；其他待规划/人工复核。p_save/p_delete 是账户写操作，明确排除，不能调用做数据权限探测。权限状态保持未验证，真实运行观察才可更新。

验证：`python3 scripts/test_tushare_structured_contracts.py`，检查闰年/日期覆盖、稳定历史身份、全部近期先行、5 类状态、12 类报表、数值字段、发现缺口、VIP 字段映射与 263 项台账一致性；没有生产网络或凭据。
