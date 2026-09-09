# 六个跨资产接口：纯合同候选

基线 `044f373` 的 registry / coverage ledger 已核对：六者均有独立官方 acquisition 名称，尚未注册，不是其他 API 的别名。本提交仅新增合同、纯规划和隔离测试；不改变当前采集数量、配置、权限或运行。官方页于 2026-09-09 核读，HTML SHA 在模块中；抓取证据 `/tmp/tushare-cross-asset-extra-docs/`。

| API / 官方页 | 全部输出列 | 隐藏 N | 单次上限 | 官方门槛 / 频率 |
|---|---:|---|---:|---|
| [idx_factor_pro](https://tushare.pro/document/2?doc_id=358) | 89 | 无 | 8000 | 5000 积分 30/min；8000 以上 500/min |
| [fund_factor_pro](https://tushare.pro/document/2?doc_id=359) | 90 | 无 | 8000 | 同上 |
| [cb_factor_pro](https://tushare.pro/document/2?doc_id=392) | 89 | 无 | 10000 | 8000 以上 500/min |
| [index_global](https://tushare.pro/document/2?doc_id=211) | 12 | amount | 4000 | 6000 积分，页面未给精确频率 |
| [sz_daily_info](https://tushare.pro/document/2?doc_id=268) | 9 | 无 | 2000 | 2000 积分，页面未给精确频率 |
| [etf_limit](https://tushare.pro/document/2?doc_id=491) | 7 | pre_close / asset_type / exchange | 3000 | 2000 积分，页面未给精确频率 |

累计 296 列全部来自官方表。字段名、源类型、默认可见性、因子默认参数保存在 `FIELD_METADATA`；`FIELDS` 和请求 selector 自动派生。三张因子表仅有少量已验证差异，复用一份完整表并应用明确差异。没有隐藏列可推测补齐；未来返回的新列及 null 仍须由既有原文/归一化路径保留。本次未实际验证账户权限，不凭 10100 积分宣称成功；运行候选上限统一保守 30/min，未来仍须服从共享账户、接口及实际响应的限流门。

`idx_factor_pro` 覆盖大盘、申万和中信，源 suffix 命名空间不能合并。`fund_factor_pro` 是场内基金；已有七位供应商历史代码保留，与六位代码不合并，`.OF` 只从 outbound 场内候选排除，不删除源记录，也不凭代码证明可交易。`trade_date_doris` 的官方类型字面是 `None`，必须保留原值，日期轴仍为 `trade_date`。转债成交额单位是万元级，指数/基金为千元级；页面未显式标货币，禁止统一缩放。因子公式参数、负数和预热 null 保留；转债正文提到 qfq/hfq，但输出表只列 bfq，不能凭此承诺复权列已覆盖。

`index_global` 的 HSI / SPX / XIN9 等是独立指数标签，不是美股 symbol。21 个当前官方代码用作发现种子，额外历史/观测代码仍可加入；成交量/额经常缺失，币种、单位、跨市场交易日历和时区没有统一合同。不得套大陆交易日或换算 UTC 日期。

`sz_daily_info.ts_code` 是中文/ASCII 板块名。官方表多数板块起点为 20080102、基础设施基金为 20210621；同页历史示例的“中小板”已不在当前枚举中，仍保留为种子。不把当前表当完整历史白名单，不擅自套用股票数量/手/千元单位。ETF 页面有复制的“股票/合约”措辞，不扩大为股票/期货权限；约 08:40 更新描述不等于可验证的历史发布时间，也不假定固定涨跌停比例。

入口：`CROSS_ASSET_EXTRA_CONTRACTS`、`iter_cross_asset_extra_jobs(config,today,identifiers=None)`、`cross_asset_extra_prerequisites(...)`、`cross_asset_identifiers(...)`、`validate_cross_asset_request`、`split_cross_asset_request`。配置使用 `cross_asset_extra_apis` 和 `cross_asset_extra_history_start`（字符串或逐 API 映射），回退既有 `history_start`。未知最早日期不会杜撰历史起点；三因子“全历史”措辞不能转换成固定日历下界。用户显式更早范围不裁掉，范围本身仍不证明覆盖。

规划先交错发出截至昨天的七天 bulk 请求，再交错发出完整配置范围的月份窗口；不按当前证券表缩窄历史。父 runtime 将饱和月份按天二分，保留父证据；终端单日可由 discovery + parent observed 的并集按合法 ts_code 细分，但永远不以观测子集证明完整 universe。无 offset/limit 输入，不造分页。饱和单码/单日、未知历史、原始时间/修订、行业成员 PIT、旧修订再扫描均保留 gap。本模块不实现分钟采集，也不把日线因子等同历史可得的研究特征。

回归：`uv run --offline --no-project --python 3.10 python scripts/test_tushare_cross_asset_extra_contracts.py`。六项测试覆盖全表指纹与隐藏列、命名空间/历史代码、月窗闰年连续覆盖和近期优先、公平交错、未知下界、更早范围、精确合法分片和非法分页。另与六份当前官方原始 HTML 解析输出逐列比较完全相等；无生产凭据或 API 请求。
