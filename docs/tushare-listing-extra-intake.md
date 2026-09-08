# 历史列表、IPO、代码映射与市场统计候选

此次核对共享台账的 263 项固定目录和 13 项额外发现（包含导航/旧页，不能等同 13 个新 API），并与 140 个已注册接口对比。仅选以下 4 个未接入接口，不重复 VIP 别名、互联互通旧页或龙虎榜接口。代码只提供纯合同和离线规划，账户权限全部 `unprobed`。

| 候选顺序 / 官方页 | 门槛、上限 | 用途与边界 |
|---|---|---|
| [bak_basic / 262](https://tushare.pro/document/2?doc_id=262) | 5000 积分、7000 行 | 每日历史股票列表，补充已退市/更名发现。官方从 2016 年起，规划 `20160101` 只是年范围边界；财务快照没有财报可知时点，不是 PIT 财务库。股本为亿股。 |
| [new_share / 123](https://tushare.pro/document/2?doc_id=123) | 120、2000 行 | IPO 发行与上市跟踪。查询范围对应 `ipo_date`；`issue_date` 是上市日，允许空或未来日期；`sub_code` 是申购代码，不能归一化为股票。历史下界未公布。 |
| [bse_mapping / 375](https://tushare.pro/document/2?doc_id=375) | 2000、1000 行 | 北交所新旧代码映射快照，保留 `o_code/n_code` 的原始 `.BJ`。`list_date` 是上市日，不能当作代码变更生效日，也不能据此合并历史行情。 |
| [daily_info / 215](https://tushare.pro/document/2?doc_id=215) | 600、4000 行 | 交易所各市场类别统计，覆盖股票/基金/债券等；完整保留 31 个文档类别及各自起日。`ts_code` 如 `SH_A/SZ_BOND_CB` 是类别标签，必须独立于股票/指数代码集合。 |

另核查的 [stk_premarket / 329](https://tushare.pro/document/2?doc_id=329) 明确与积分无关，需独立开通；用户列出的权益未证实包含它，因此暂未列入本次纯合同。此项依然是全范围待权限核实义务，未从目录删除。其他接口同样不能仅因 10100 积分超过页面门槛就认定已授权。

## 输出与计划接口

仅新增 `tushare_listing_extra_contracts.py`、专属测试和本文。导出 `LISTING_EXTRA_CONTRACTS`、`iter_listing_extra_jobs(config, today, identifiers=None)`、`listing_extra_prerequisites(...)`。未来组名建议 `listing_extra`；配置为 `listing_extra_apis`、`listing_extra_history_start`（字符串或每 API 字典），回退 `history_start`。

54 个官方输出列全部进入 `requested_fields/required_fields/extra_fields`；未标记隐藏列。非身份字段允许空、负值和零，不自行填充。实际集成必须显式发送字段、检查返回列，并保留未知新增列。`daily_info.tr` 文档称深圳暂无此列：允许值为空，但若真实整列缺失，须保留 `schema_gap` 和原始响应，再核查市场特定合同，不能当作字段已获取。

近期先处理最近 7 个自然日，再轮转历史任务。`bak_basic/daily_info` 按精确交易日查询，不先按当前股票/开市日过滤；`new_share` 按发行日期的月内范围，`bse_mapping` 只做无筛选快照。`new_share` 另做一个无筛选近期发现请求，接收供应商已提供的未来发行信息，不捏造未来截止日期；达到上限时该请求仍不完整。日期 anchor 和有限扫描复用现有外层机制，纯 planner 不持久化游标。

自然键候选：`bak_basic(trade_date,ts_code)`、`new_share(ts_code,ipo_date,sub_code)`、`bse_mapping(o_code,n_code)`、`daily_info(trade_date,ts_code,exchange)`；全部要求保留不同源行与原始观察，避免修订值直接消失。内容哈希不能证明同值独立事件数，也不能替代可知日期。

## 必须保留的接入缺口

- `bak_basic` 饱和时需要历史/退市/T 股票主表与已观察列表代码并集；当前接口目录并不证明该集合齐全。现有股票发现必须另接新增源。
- `new_share` 日期范围只按发行日拆分；单日到 2000 行时没有合法 `ts_code`、offset 或 limit 参数。无筛选发现请求也没有可直接二分的边界，两者终端饱和都应保持 blocked。发行很久后补充上市日期等修订，不保证被 7 日范围或截断快照发现。
- `bse_mapping` 无历史日期输入。页面写“总量 300 以内”不构成永久保证；达到 1000 时按已观察旧码/新码重查不能证明漏掉的映射不存在。源上市日期和采集观察时点分别保留，代码变更生效区间仍未知。
- `daily_info` 31 类各有起日，最早为 `19901219`；这是文档已知类别范围，不证明后来新增/合并/停用类别齐全。精确日到上限需要按 SH/SZ 与独立市场类别分区，不能使用股票 fanout。该纯候选没有假装现有通用运行器已接好此分区。
- 全部未公开 offset/limit。历史范围、字段实测、标签 namespace、权限、PIT 和旧修订仍待运行验收，本提交不改 runtime、catalog、ledger 或生产。

## 精确目录提取差异

固定 `daily_info` 目录把 31 个板块代码误记入 `input_fields`。纯合同将参数限定为 `trade_date/ts_code/exchange/start_date/end_date/fields`；板块代码和其起日归入 `DAILY_INFO_STARTS` 元数据。`fields` 是顶层字段选择参数。保留目录原文哈希 `15df88d3827e3e6b28fa904833651a052ccb0495690aa9186cfd7a2bd7ed8010` 和全部分母，留给父任务明确修正；本批没有编辑目录。其余 3 页字段与固定目录一致。

离线复验：`python3 -S -B scripts/test_tushare_listing_extra_contracts.py`。8 个测试覆盖所有字段/输入、完整类别起日、日期轴、闰日连续性、未知下界、快照与历史区分、惰性轮转及非法配置；不导入 Pipeline，不访问账户或数据目录。
