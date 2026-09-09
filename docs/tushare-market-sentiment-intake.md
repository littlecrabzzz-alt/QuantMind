# TDX、KP 与跨市场热榜：7 API 纯候选

基线 `044f373`，2026-09-09 官方逐页核对；未注册、启用或调用生产。仅新合同、纯 planner 和测试，未来 family 为 `market_sentiment`。它们补充板块与市场关注度数据，不构成 RRG 行业成分的历史时点证据。

| 官方接口 | 全输出列 | 单次上限 | 文档积分条件 | 请求范围与身份 |
|---|---:|---:|---:|---|
| [tdx_index 376](https://tushare.pro/document/2?doc_id=376) | 9 | 1000 | 6000 | 精确 trade_date；概念/行业/风格/地区四类 idx_type |
| [tdx_member 377](https://tushare.pro/document/2?doc_id=377) | 4 | 3000 | 6000 | trade_date 或 start/end；TDX板块 + con_code成员 |
| [tdx_daily 378](https://tushare.pro/document/2?doc_id=378) | 38 | 3000 | 6000 | trade_date 或 start/end；TDX板块行情 |
| [kpl_list 347](https://tushare.pro/document/2?doc_id=347) | 24 | 8000 | 5000 | 日期及涨停/炸板/跌停/自然涨停/竞价五个 tag |
| [kpl_concept_cons 351](https://tushare.pro/document/2?doc_id=351) | 7 | 3000 | 5000 | 仅精确日期；KP题材 + con_code成员 |
| [ths_hot 320](https://tushare.pro/document/2?doc_id=320) | 11 | 2000 | 6000 | 九市场 × is_new Y/N，保留 rank_time |
| [dc_hot 321](https://tushare.pro/document/2?doc_id=321) | 8 | 2000 | 8000 | 四市场 × 人气榜/飙升榜 × is_new Y/N |

全部 **101** 列目前都标默认Y；合同显式请求并要求全列，允许非身份字段真实null、未知额外字段和有符号值。`FIELD_METADATA` / `INPUT_METADATA` 保存完整字段名、类型、默认/必填开关和原始含义，`SOURCE_HTML_SHA256` 保存页SHA。原文与表格仅 `/tmp/tushare-market-sentiment-docs/{376,377,378,347,351,320,321}.{html,json,txt}`。没有默认N列也不能把 `fields=''` 当完整性证明。

**目录差异保留**：tdx_daily官方38列，现有目录32列，漏 `3day/5day/10day/20day/60day/1year` 六个数字起首字段。合同全部保留；固定读取现有字段引用支持这些名字，不能改名。本候选不编辑catalog或ledger，定点纠正是后续集成义务。其他六接口输入/输出与目录一致。KP351表格是 `con_name/desc/hot_num`，但示例头为 `ts_name` 且缺后两列；不能假定别名兼容。实际缺列须报schema gap并保留新增 `ts_name`。示例正好3000行，更不能据此认定全题材全集。

导出 `MARKET_SENTIMENT_CONTRACTS`、`iter_market_sentiment_jobs(config,today,identifiers=None)`、`market_sentiment_prerequisites(...)`。配置 `market_sentiment_apis`、`market_sentiment_history_start`（字符串/API映射，回退 `history_start`）。七页均没有精确最早日期；默认仅近7个日历日，显式历史范围才回填，不把示例2024/2025日期当起点，也不把配置1990当最早源数据。近期然后历史，按API逐条轮转、惰性生成；默认全部类别每日46个精确请求，七日322是规划数量，**不是实测耗时或吞吐**。历史沿用精确日期；只有377/378/347支持日期范围，合同为未来饱和分片保留合法二分参数，未猜offset/limit。

板块角色严格分开：TDX代码 `xxxxxx.TDX`、KP `xxxxxx.KP` 独立于THS/DC及股票；不能用名称或股票形状推导对应关系。TDX类别写的是“地区板块”，不同于DC参数“地域板块”。TDX/KP成员需保留原始 `con_code` 和SH/SZ/BJ/T/退市来源；未知市场拼写继续验证。`tdx_indices`、`kpl_concepts` 饱和发现必须纳入历史/已观察退市板块；日期全市场请求可以先采，缺主目录不阻初始任务，但观察代码集合不能证明完整。单板块饱和所需 `con_code` 第二维虽有合法输入，完整历史成员宇宙和通用第二维接线仍是gap。

热榜全部市场必须保留：THS为热股、ETF、可转债、行业板块、概念板块、期货、港股、热基、美股；DC为A股市场、ETF基金、港股市场、美股市场。输出 `data_type` 不能替代请求 `market/hot_type/is_new`；这几个维度纳入 immutable request identity，天然键另含日期、代码、rank_time与rank。数字/股票形状也不能把外国股票、期货或板块强制转A股。纯模块未实现跨市场规范化，运行集成必须按请求市场保留 namespace/source_ts_code。故未声明危险的统一stocks饱和回退；缺分市场历史代码全集或单股饱和均继续gap，没有合法rank_time/排名/日期范围分页。

热榜文案称盘中4次、盘后4次、最晚22点，而参数说明N每2小时、Y22:30；真实完整采集时间表/时区未验证。日期调度无法证明全部盘中版本，Y与N有重叠也不能合并为同一次观察。DC `rank` 含“排行或者热度”，不统一当序号。KP五tag默认不能只拿涨停，字符串主题/原因/封板时间与同日多行保持，不反推PIT成员或即时可知性。

权限全部unprobed，10100积分不是实际授权证据。KP347明确5000档200次/分、每日10000次；8000档500次/分、日总量不限制，但仍需实际权限/共享限频验证。其他页未给每分钟/日总量及独立权益，保留未知；统一30rpm仅本地保守上限。TDX量为手、成交额为万元，但文档说明期货指数该列是持仓量；不能跨资产统一解释。股本/市值多为亿单位；`bm_buy_net`元、`bm_net`单位未给；`rise/pe/pb`是字符串。KP/热榜金额、热度、排名、外币价格的未声明尺度/算法都保留，不套其他接口单位。

验证 `python3 -B scripts/test_tushare_market_sentiment_contracts.py`：全字段及六目录遗漏、46类别组合身份、近7日/显式历史闰日连续且无重复、惰性1990范围、合法日期二分保留原过滤器、真实既有response assessor的缺列/满cap拒绝、数字列引用、跨市场/PIT/权限gap、配置校验。无网络数据请求、运行模块或覆盖台账修改。
