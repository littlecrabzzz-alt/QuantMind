# 实时8接口纯候选（默认关闭）

只新增纯合同、规划器和离线测试，不注册、不排生产任务。`rt_k` / `rt_etf_k` 复用既有 `tushare_discovered_contracts.py` 的契约副本及请求/epoch helpers；原模块保持不变，新副本要求全部已知列存在。共 **87输出列，8个默认隐藏列**，未知列、空值和来源原串必须保留；字段存在不等于值非空，也不按文档类型截断小数。

| API / 官方页 | 输出列 / 隐藏 | 合法输入及请求分区 | 历史与限制 |
|---|---:|---|---|
| stk_auction /369 | 9 /0 | ts_code、trade_date、start_date、end_date、ts_type；无类型/STK/ETF三种请求身份分别保留 | **当前文档支持202501起历史**，并称当日09:26–09:29可获取；8000行，独立权限 |
| rt_etf_sz_iopv /454 | 12 /0 | 可省ts_code获取深市全集，可单/多ETF代码 | 实时；5000行，独立权限；页面“完全覆盖当前总量”不能证明账户实际覆盖 |
| rt_idx_k /403 | 10 /0 | 必需ts_code，可单/多代码或通配符；纯计划按已存交易所指数逐码 | 实时；未披露cap/rpm，1000仅本地保护阈值 |
| rt_idx_min /420 | 8 /0 | 必需ts_code、freq；实际交易所指数逐码×5频率 | 实时；1000行；输出time类型写None，且没有freq输出列 |
| rt_sw_k /417 | 10 /0 | 可省ts_code取最新申万截面，可单/多指数 | 实时；未披露cap/rpm；20260908公告移除pct_change，仍收到时作为额外源列保留 |
| rt_fut_min /340 | 10 /0 | 只ts_code、freq；实际期货合约逐码×5频率 | 实时；页面500rpm，cap未披露；输出code/freq/time，不能改称源ts_code |
| rt_k /372 | 15 /5 | 必需ts_code，可多代码/通配符；复用已存股票每100码分批 | 实时；6000行；100码是操作批次而非官方最大代码数 |
| rt_etf_k /400 | 13 /3 | ts_code、topic；复用SH `5*.SH`+HQ_FND_TICK、SZ `1*.SZ`示例及已发现例外代码 | 实时；cap未知；topic表称必需但SZ示例省略，该矛盾保留 |

分钟freq严格为 `1MIN/5MIN/15MIN/30MIN/60MIN`，全部五种默认分别规划，不自动重采样。rt_k隐藏ask_price1/ask_volume1/bid_price1/bid_volume1/trade_time；rt_etf_k隐藏ask_volume1/bid_volume1/trade_time。完整输入、字段类型、中文描述及Y/N逐列位于合同 `INPUT_METADATA` / `FIELD_METADATA`。

## 日期、身份与来源边界

- 七个实时接口没有一般历史日期参数。`realtime_extra_snapshot_epoch` 复用显式UTC格式YYYYMMDDTHHMMSSZ，并校验属于给定Asia/Shanghai日；它只是采样槽的幂等标识。纯代码没有安装定时器，不能把旧槽重新执行后当作过去的观测。未来执行层须校验到期/过期、记录真实请求响应时间；不能将排队时间当源时间、假设固定交易时段或把最新close当日终收盘。
- `stk_auction` 是有证据的历史例外：近期7个日历日逐日，历史按连续月窗、每窗无类型/STK/ETF三次合法请求；不硬筛周末。起点设置为 `realtime_extra_history_start`（字符串或仅stk_auction映射），兼容history_start，无配置时20250101只是官方月级声明的请求边界。显式更早scope仍保留，未来日期拒绝；低于cap、空日期或页面起点都不能证明真实历史无缺口。
- 369示例含ETF及123039.SZ这类转债代码；未分类请求不能直接归A股。保留ts_type缺省的请求身份和source代码，资产类别需真实主数据确认。price文档int但示例有23.240/1.211，保留小数；ETF换手率/量比可空。股数、万股、元、份、百分数分别按原字段描述保留。
- 规划依赖stocks、etfs、indexes、sw_indexes、minute_futures。复用实际来源代码读取；不把stocks跨用作指数/ETF/期货全集，保留T、大小写等来源特征。已知未映射/不支持代码留 `unsupported_source_codes` gap，非凭通配符宣称全历史资产全集。产品/连续合约不能猜成当期主力，主力须真实fut_mapping来源。
- 命名空间建议沿用已集成语义：FUND:原码、IDX:原码、FUT:原码；股票须确认资产后再转交易所前缀。rt_fut_min保留source `code`；输入叫ts_code并不改变输出列名。所有实时观察保留_observation和来源time，分钟freq及auction ts_type/ETF topic用现有_request_identity机制；不要新增伪源字段。合法省略ts_type或SZ topic也必须明确区别于来源缺失，未来接线不能把合法无过滤请求误判为失败。
- 所有8项独立权限均unprobed。10100积分、新闻/公告/研报购买不替代实时授权；唯一明确频率上限是340页面500rpm，其余未披露，30rpm只操作上限。满页无offset/limit或时间二分；只有auction可用合法日期范围二分。按真实代码再拆仍不保证同一原始时刻；缺主数据或单码满页继续gap。

## 独立邻接API义务（本批不执行，不能漏计）

1. **rt_idx_min_daily**：页420正文明确命名，且给出`ts_code='399300.SZ',freq='1MIN'`调用。支持单个指数当日开盘以来分钟，不可多指数；freq同上述五种，未声明date参数。它是独立API，不是rt_idx_min查询别名；权限、cap及共用输出表是否完全一致待验证。
2. **rt_fut_min_daily**：页340另有明确标题和输入表。必需ts_code（一次一个合约）、freq（同五种）；可选date_str格式YYYY-MM-DD，默认交易当日，声称可回溯一天。未说明“一天”是交易日还是日历日，尤其夜盘边界未知，不能扩为多年历史。当前catalog340把该表date_str混入rt_fut_min输入；本合同只给实时接口ts_code/freq，未改全局catalog/parser。

父后续将这两个实际API加入发现清单，不能受既有“13个发现”计数限制。本候选保留 `ADJACENT_API_OBLIGATIONS` 便于接续，未静默调用或缩减原scope。

## 本地来源证据与验证

复用已保存官方HTML，未发新HTTP。369/454/403/420/417/340原文在 `/tmp/tushare-full-schema-audit-20260909/<doc>.html`；372/400在 `/tmp/quantmind-discovered-contracts/<doc>.html`。完整SHA也内置合同：

| doc | HTML SHA256 |
|---|---|
|369|1569d43c483eeccfa03c7ed705493bccd519767273ff90088f08997eb48f2a7f|
|454|041a3656de6dc016e72c02ae8de7cbd0dbec8391a1858722994af3c10add1790|
|403|7199e8b081500db5e789561c04192f2c31a78c71d5f7f3596e989825e772cf26|
|420|a6eb3ee102aa6a8446776137b15158b507ed7aa7d8d75badb8cff4da423ed879|
|417|4cb7963c01b5592ce0e62c40baa504f35933cc0d76957e6fb1b0255de48c0399|
|340|5f5012e5b93f067a93a2c82b38bd81e92194a18606b47a930fef63e79a882bb7|
|372|58905ec12e31c14a168bb781892ee3c89547d879252ac9ebbaad1062bb755912|
|400|4395c969142c0818405e4ce17fea6a1bbefde370a287edfa52c05253b5e5c478|

离线命令：`python scripts/test_tushare_realtime_extra_contracts.py`。验证87列/8隐藏、复用原契约无修改、默认关闭、无伪历史、频率身份、UTC跨日/过期日、命名空间发现、auction三类型月窗连续/闰日/首尾、两个邻接API义务及catalog输入差异。

后续运行接线必须先解决实时任务过期和调度隔离：不要因每个新快照epoch重置auction未完成历史游标；不要直接把这个混合纯生成器当成已支持实时dispatch的证明。可以按明确api子集复用同一合同，但消费/快照时效与auction历史状态应分别审核。默认 `enable_realtime_extra=false`，当前没有注册、权限探测、自动采样、固定版消费验收或研究准入。
