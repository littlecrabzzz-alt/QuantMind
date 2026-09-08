# 期货运行接缝与下一批7接口（只读交接）
- remaining_markets / Mac / codex/tushare-other-markets；只读核对共享main 8249f6c，父持有registry/pipeline/store，text持有normalize/_dataset；本轮未改任何运行文件、无API/生产调用。仅此coord记录。
- 临时内存DuckDB + 临时Pipeline复现：周报默认日期筛选报Unknown stored field: None；显式date_field=week_date返回1行。fut_basic夹具IF.CFX和IFL.CFX，identifiers仅返回continuous=['IFL.CFX']，没有futures_indexes。date_children对weekly_monthly的20240228..20240301保留freq且正确覆盖闰日；weekly_detail start_week/end_week返回None，符合合同禁用通用日拆分。

## 期货映射
| API | 默认筛选日期 / 标的 | 必须保留或补齐 |
|---|---|---|
| fut_trade_cal | cal_date / exchange | DATE_FIELDS已有cal_date；无ts_code，codes筛选须code_field=exchange；保留0休市与pretrade_date，不能表示夜盘session |
| fut_daily_adj | trade_date / ts_code | 原始主力/连续代码、source_ts_code；由本API全部raw ts_code加入futures_continuous可补IF.CFX，不能仅靠L后缀 |
| fut_weekly_monthly | trade_date=周期标签 / ts_code | end_date=计算截至；key中freq/end_date均保留。按实际截至筛选需显式date_field=end_date。reader现无精确freq通用参数，调用方必须选择week/month或分开读取，不能直接混频用于回测 |
| fut_holding | trade_date / symbol+exchange | 无ts_code，代码筛选须code_field=symbol；broker非稳定ID，distinct源行保留；SHFE包含INE，不可重复求和 |
| fut_index_daily | trade_date / .NH ts_code | 新futures_indexes从本API原始响应发现，保留历史/退役；不能从商品代码臆造.NH。当前normalize保留CU.NH及source_ts_code，无需StockCodeUtil |
| fut_weekly_detail | **week_date** / prd+exchange | DATE_FIELDS缺week_date，应增加；raw week为供应商周期，旧样例20199，不能按YYYYMMDD/ISO解析。code_field=prd；币额单位亿元，与其他日线不同 |
| ft_limit | trade_date / ts_code | cont为品种，m_ratio为最低保证金百分比；文档“TS股票代码”为期货字段标签笔误，不能据此归股票 |

持仓饱和：当前split_request只支持单param字符串fanout，无法安全承载exchange+symbol。需父显式组合分片，从raw fut_basic.symbol/fut_code+exchange和fut_holding响应的symbol+exchange取得，保留大小写与退市记录；不要截取ts_code臆造，不能用无交易所的futures_products证明完备。SHFE覆盖INE语义需按本接口实测保留，不做全局exchange改写。终端饱和继续gap，部分已观察symbol不证明全历史覆盖。

## 下一批顺序（263台账中均planned/unverified，准确API各1，无别名）
| 顺序/API/官方 | 建议规划、字段重点、上限及缺口 |
|---|---|
| 1 margin [58](https://tushare.pro/document/2?doc_id=58) | 9字段；key trade_date+exchange_id；逐日全市场或历史日期范围，exchange_id=SSE/SZSE/BSE。4000；金额元、rqyl/rqmcl混合股份手。上一日次晨更新，深/北周五下周一，近期至少7日重叠。 |
| 2 margin_detail [59](https://tushare.pro/document/2?doc_id=59) | 11字段；trade_date+ts_code，逐日，饱和代码分片。6000；name仅20190910后有，早期必须nullable；保留rqchl/rqmcl/rqyl单位区别。文本称沪深同时提北交所，覆盖要实测。 |
| 3 margin_secs [326](https://tushare.pro/document/2?doc_id=326) | 4字段；盘前trade_date+ts_code+exchange，6000；含ETF及沪深京，发现依赖须stocks+funds+父响应观察，不能只fanout股票。 |
| 4 slb_len [331](https://tushare.pro/document/2?doc_id=331) | 6字段；key trade_date，无股票依赖，历史日期范围可二分。5000；ob/auc_amount/repo_amount/repay_amount/cb均亿元。不同于目录中标停的slb_sec/slb_sec_detail/slb_len_mm，不能作为它们别名。 |
| 5 block_trade [161](https://tushare.pro/document/2?doc_id=161) | 7字段；逐trade_date全市场，1000后代码分片；至少日期/ts_code之一。交易无稳定ID，同日同买卖营业部不同price/vol/amount不得粗键覆盖；甚至完全同值两笔是否可辨仍未知。vol万股，amount页面未明确单位。 |
| 6 pledge_detail [111](https://tushare.pro/document/2?doc_id=111) | 14字段均显式含is_buyback；1000，输入start/end是公告范围，输出同名字段是质押起止，不可混用；ann_date轴规划，超限分stock。缺事件ID，应distinct源行，release_date/解押后修订独立保留。 |
| 7 pledge_stat [110](https://tushare.pro/document/2?doc_id=110) | 7字段；key ts_code+end_date。1000，只有ts_code/end_date输入，**无start_date**；按股票历史发现或准确截止日，不能套范围分片，也不能从示例断言周频/最早日期。股票单次饱和后需截止日探测，未知完整性保留gap。 |

上述7官方详情均写2000分起（secs另列5000无总量限制；slb_len列200/500次每分钟），但账号仍unprobed；没有独立授权证明、没有offset/limit输入、没有公开最早日期。选择理由是现有stocks/funds发现和日/公告轴分片可复用；不删目录其他分类/标停历史，后续依然计入全263覆盖目标。
