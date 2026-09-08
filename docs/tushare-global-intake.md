# 港美股、A股与指数周月线接入契约

本批新增 17 个官方目录 API 的静态契约与纯规划器；接续 `tushare-integration-plan.md`。2026-09-09 核对官方文档和 `config/tushare-catalog.json`。未调用生产 API，未验证账号权限，未写业务数据或部署。积分达到门槛不等于实际成功，更不能推定港美股独立行情权限已经购买。

## API 范围与文档证据

| API / 官方文档 | 每次上限 | 文档权限 | 历史下界与范围 |
|---|---:|---|---|
| [hk_basic](https://tushare.pro/document/2?doc_id=191) | 未给数值，称可取全部在交易列表 | 2000 积分 | L/D/P 均规划；不按市场类别筛选 |
| [us_basic](https://tushare.pro/document/2?doc_id=252) | 6000，分页 | 5000 积分正式权限 | 不限分类 + L/D/P 分页；包含未知分类 |
| [hk_tradecal](https://tushare.pro/document/2?doc_id=250) | 2000 | 2000 积分 | 起点未明；交易日与休市日均保留 |
| [us_tradecal](https://tushare.pro/document/2?doc_id=253) | 6000 | 5000 积分 | 起点未明；交易日与休市日均保留 |
| [weekly](https://tushare.pro/document/2?doc_id=144) | 6000 | 2000 积分 | 起点未明；每周最后交易日更新 |
| [monthly](https://tushare.pro/document/2?doc_id=145) | 4500 | 2000 积分 | 起点未明；月线 |
| [stk_weekly_monthly](https://tushare.pro/document/2?doc_id=336) | 6000 | 2000 积分 | 起点未明；week/month 两种频率，每日更新 |
| [stk_week_month_adj](https://tushare.pro/document/2?doc_id=365) | 6000 | 2000 积分 | 起点未明；含原价、前/后复权 OHLC |
| [index_weekly](https://tushare.pro/document/2?doc_id=171) | 1000 | 600 积分 | 起点未明；所有已发现指数作为满页拆分范围 |
| [index_monthly](https://tushare.pro/document/2?doc_id=172) | 1000 | 600 积分 | 起点未明；每月更新 |
| [index_dailybasic](https://tushare.pro/document/2?doc_id=128) | 3000 | 2000 积分 | 明确从 2004-01；默认 20040101 |
| [hk_daily](https://tushare.pro/document/2?doc_id=192) | 5000 | 独立权限 | 起点未明；约每日 18:00 更新 |
| [hk_daily_adj](https://tushare.pro/document/2?doc_id=339) | 6000 | 独立正式权限，120 积分试用 | 起点未明；全市场，不限制当前上市状态 |
| [hk_adjfactor](https://tushare.pro/document/2?doc_id=401) | 6000 | 港股日线权限开通后获得 | 起点未明；每日滚动刷新 |
| [us_daily](https://tushare.pro/document/2?doc_id=254) | 6000 | 独立正式权限，120 积分试用 | 描述为全部股票全历史，没有确切日期 |
| [us_daily_adj](https://tushare.pro/document/2?doc_id=338) | 8000，分页 | 独立正式权限，120 积分试用 | 起点未明；全市场，不按交易所筛选 |
| [us_adjfactor](https://tushare.pro/document/2?doc_id=402) | 15000 | 美股日线权限开通后获得 | 起点未明；美股收盘后滚动刷新 |

每个契约的 `extra_fields` 包含该页全部输出字段，调用方应合并为顶层 `fields` 选择器；保留额外返回原始字段。特别包括 `us_basic.enname` 和 `us_daily.change/turnover_ratio/total_mv/pe/pb` 等默认隐藏字段。所有非关键字段可空，不能因官方示例中的空 `close_price` 丢掉复权因子记录；港股价格高低关系存在官方允许的特殊情形。

操作频率统一保守设为 50 次/分钟，交给父共享限流器再取更低全局上限；不是当前账号频率断言。[总权限页](https://tushare.pro/document/1?doc_id=290)列美股日线 500 次/分钟、8000 行，而 `us_daily` 自身页面列 6000 行，本批对原始日线保留更小的 6000。其他单页未提供明确每分钟频率，元数据为 `None`，不得解释为不限量。

## 父 registry / worker 接入

导入以下三个公共对象即可，模块只依赖标准库和已经集成的 `tushare_structured_contracts._contract/_parse`：

```python
GLOBAL_CONTRACTS
iter_global_jobs(config, today, identifiers=None)
global_prerequisites(identifiers=None, enabled_apis=None, config=None)
```

- 将 `GLOBAL_CONTRACTS` 注册为新 contract family；所有条目 `permission_status='unprobed'`。父逐接口探测并记录权限拒绝，不因单个独立权限缺失停掉其他接口。
- `config.global_apis` 可选 API 列表，空列表明确关闭本批。`global_history_start` 可为 `YYYYMMDD` 或 API→日期映射，未指定项回退显式 `config.history_start`，最后回退已知官方起点。只有 `index_dailybasic` 有可证实的精确下界；其余没有配置时仍规划近期并返回历史缺口，不猜起始日。显式范围仍不能证明更早历史不存在。
- `today` 为父确定时区后的 `date/datetime`。近期为今天及前六个自然日，priority=20，epoch 默认为 YYYYMMDD，可用 `planning_epoch` 固定观察身份；历史 priority=40、epoch=`history`。全部近期任务在历史之前，历史按日期交错不同 API。父持久化规划游标时必须同时固定 today/config/universe，不能随日期变化沿用旧位置。
- 输出请求只含 `{api_name, params, priority, epoch}`；不添加 token、网络、DB、调度状态。`fields` 是顶层请求字段，不塞入 `params`。父持久队列负责去重、限流、重试、分页、满页拆分和发布。
- 普通行情按 `trade_date` 全市场逐自然日枚举，包含周末，防止月线官方示例的自然月末标签被交易日过滤漏掉；日历用 `start_date=end_date`，不设 `is_open`。所有日期范围完整生成，父可以分页消费生成器。尚未基于验证完整的当地日历压缩空请求。
- `stk_*` 同时枚举 `freq=week/month`。未来周五、月末标签补入近期请求；`trade_date` 是周期标签，`end_date` 是计算截至日期，两者不可互换。KEYS 包含 `ts_code,trade_date,freq,end_date`，每次观察仍要完整版本化。
- `identifiers` 支持 `stocks/indexes/hk_stocks/us_stocks`，值为原始代码字符串或含 `ts_code`（指数亦可 `index_code`）的发现记录。原始后缀或美股 ticker 仅在供应商请求边界使用，不能直接充当 QuantMind 内部市场编码。US 不补 `.US`，HK 保留五位数字；不能把 US ticker 中的点或连字符误当中国交易所后缀。
- 本层全市场请求不依赖已知标的才开始；每个行情的 `saturation_fallback/saturation_param` 指向相应发现 family。父 reader/queue 的 `identifiers()` 需增加 `hk_stocks/us_stocks`，保留退市、暂停上市、历史观察中消失的代码。`global_prerequisites` 返回缺少拆分标的与未知历史边界；这些不是阻止独立近期请求的硬门槛。非空列表不等于发现完整，父仍须完成分页和范围审计。
- `us_basic`、`us_daily_adj` 提供 `pagination`，初始请求带 `limit`，第一页省略 `offset`；后续必须验证分页原点、重复页、终止页。日期窗满页先二分日期，单日满页按全量证券拆分；始终保留原满页观察及未证实范围，不把成功的几个子请求当成全覆盖。

## 持续缺口与修订语义

1. `us_basic` 输入表写 `list_stauts`，分类描述为 `EQ`，示例为 `EQT`。本批保留供应商表内拼写；所有分类不设过滤，额外执行 L/D/P 范围。实际服务若忽略拼错参数，可能重复返回默认上市数据，必须通过响应分布验证，不能以 HTTP 成功宣告退市完整。页偏移示例称 1 为第一行，当前父通用分页从零计数，边界须实测确认。
2. `us_daily_adj` 参数表 `exchange`，示例误写 `exhange`；本批不按交易所过滤。`us_adjfactor` 示例有 `ARC` 且恰好 15000 行，因此绝不能只分 NAS/NYS/OTC 或把整页当全日完整。
3. `hk_daily_adj/us_daily` 描述支持分页，但参数表未列游标；不虚构参数，先用已文档化的日期/标的拆分。`hk_basic` 无数值上限，6000 仅作保守报警线，`row_cap_verified=False`，达到该值的发现范围仍是 gap。
4. `index_dailybasic` 描述列六类指数，示例更多；按日期取全部返回，不人为截成六个。其指标不保证覆盖任意指数。未知历史起点、旧代码/证券再上市和供应商历史修订仍需进一步证据。
5. 港美股 `*_daily_adj` 文档的价格仍需乘 `adj_factor` 得前复权价格，不得再次把乘后的价格标记成原始 close。`*_adjfactor.cum_adjfactor` 是单独字段，不能无证据直接替代前者。
6. 复权因子会重写旧日期。近期七天重观察只刷新近期，父需另行安排周期性全历史复核 epoch；不可在稳定 `history` 去重下声称旧复权因子永远最新。全量观察快照可重现采集时刻，并不等于供应商 PIT，也不能还原采集前未保存的修订。
7. 权限、交易所覆盖、最早可用日、分页边界均未经本任务实测。调度、数据大小/耗时、云端写入与本地镜像由父统一处理。

离线验证：`python3 scripts/test_tushare_global_contracts.py`，覆盖全字段目录一致性、L/D/P、未知分类、分页元数据、闰日/完整范围、近期优先、默认已知历史起点、未知下界缺口、周期未来标签、代码/退市范围、输入校验与无网络规划。
