# 实时8 + 相邻回放2运行候选

基线 `7b8a970`，仅独立 worktree 候选。无生产调用、启用、配置修改或重启；`p_list` / `p_get` 没有接入公共 reader。保留纯合同中的权限、字段、历史、分页、PIT 和时间边界缺口。

## 三个独立运行 scope（全部默认 off）

| scope / enable flag | API | 规划配置与身份 |
|---|---|---|
| realtime_auction / enable_realtime_auction | stk_auction | realtime_auction_apis 仅该 API；realtime_auction_history_start 复用原纯合同起点规则，fallback history_start / 20250101请求下界；近期7日+月历史，原始空/STK/ETF三变体 |
| realtime_extra / enable_realtime_extra | rt_etf_sz_iopv、rt_idx_k、rt_idx_min、rt_sw_k、rt_fut_min、rt_k、rt_etf_k | 显式 realtime_extra_snapshot_epoch 当前UTCslot；可选 realtime_extra_frequencies，5种大写完整默认；仅快照 |
| realtime_replay / enable_realtime_replay | rt_idx_min_daily、rt_fut_min_daily | 显式 realtime_replay_snapshot_epoch 当前UTCslot；realtime_replay_frequencies；realtime_replay_futures_scope 默认current |

`stk_auction` 在运行态从原 pure realtime_extra 组分离。不可再把它放进运行配置 realtime_extra_apis；没有现存生产配置迁移，因为本批尚未启用。这样新的 snapshot epoch 不会重置竞价历史尾部游标；专项测试证明 history:realtime_auction 的未完成 offset 继续推进、signature 不变。不会改变其他旧族 policy hash。

实时规划不会生成 epoch：必须提供显式同北京时间日期的 UTC slot。过期/格式错配置只抑制对应实时请求并记 gap，不修改配置、不影响竞价历史；更换合法 slot 才产生新任务 ID。没有安装新定时器、下载器或独立 worker，不通过静态历史配置每轮复放旧快照。未来启用时必须明确由谁产生下一 slot 和频率预算。

## 发送前检查及恢复

`run()` 仅在现有 next_job 之后、capture_sample 之前，对新增9个 snapshot/replay API 检查任务自身 epoch 和实际 dispatch 时间。未启用/未选择的接口为 snapshot_disabled；格式/日期错为 snapshot_invalid_epoch；未来时间（包括同日未来）为 snapshot_future_epoch；按Asia/Shanghai跨日为 snapshot_expired。拒绝状态和 capability 的安全原因持久化，0HTTP、不增加 attempts/tries、不伪造响应、不覆盖旧 raw。保留原 job / gates / 历史，新的 epoch 用既有稳定 id 规则产生不同任务，旧拒绝任务不会挡住新 slot；同 epoch 不被偷偷重置重试。

竞价的 history / trade_date 任务及全部旧 API 不走该 guard。对旧 daily 和竞价 history，用有/无guard的隔离对照验证 capture输入与持久化 job 字节完全一致。next_job、tick、配置读取、publish、通用history预算未修改。

## 来源、字段和固定版读取

- 10个 API 共105已知字段（含已知defaultN）全部显式请求，不受 catalog340 将 daily 输入 date_str 混入的旧解析影响。任何额外返回列仍完整保存；缺必需列保持既有检查。rt_fut_min_daily 与 rt_fut_min、指数两接口各自独立 dataset，绝不做别名。
- source-only发现使用 jobs∪attempts 的现有原文机制，只增加新族来源投影；按纯框架复用既有历史/退市/T股票、ETF、指数、申万及实际期货来源。新来源不反向扩大旧stocks等家族，未typed竞价来源不推断成A股。
- 指数 IDX:，ETF FUND:，期货 FUT:，股票合法源代码采用原有内部前缀并保留T。未typed竞价 AUCTION_UNTYPED:原码；即便看似股票/ETF/可转债也不猜资产。同码空/STK/ETF请求身份独立。显式STK请求分类是否真的有效仍需实际过滤验收。
- 期货源列 `code` 保留为 source_code，并投影为 FUT:；同时给出相同canonical ts_code/source_ts_code供统一固定reader选码。原始 request.ts_code 保留在不可变观察/请求身份。分钟源 code/freq 与合法单码或普通实时多码请求不匹配时拒绝规范化，原文已保存，不静默改正或标作通过。
- 合法可选身份：竞价ts_type、深圳ETF的topic、期货daily的date_str，缺省记显式null；其余freq/源代码字段仍必需。normalize和固定reader都按不可变观察核验，空维度不合并为已传值。所有新身份/资产投影只作用新10接口。
- 默认date轴来自各合同：竞价trade_date；分钟time；其他实时trade_time。新的 time/trade_time 过滤复用秒精度参数（YYYY-MM-DD HH:MM:SS或日期整日）；若源只有钟点、缺时间或无法解析，仍能读完整原文行，但过滤报 realtime_timestamp_unverified，不能臆造日期/时区后声称不存在数据。没有改写source时间字段或冒充交易/PIT时间。
- 期货上一交易日 eligibility 尚无自动可信来源生成器。运行adapter传空验证窗口，选择current_and_verified_previous仍只跑current并保留前日gap；后续需要实际端点/交易所session的日期对照来源才能接前日窗口，绝不从today-1/股票日历/手填配置生成。

固定reader仍无上游回退；镜像安装名单增加 discovered/realtime_extra/realtime_replay 纯模块，读取不依赖Tushare token。权威数据库schema和manifest格式不变，没有数据迁移。

## 验证与审查范围

新专项覆盖10接口capture→normalize→publish→store全列/未知列/源代码；5freq/3竞价变体/可选date身份；必需freq缺失阻读；源频率不一致保留raw并拒绝投影；未知时间不猜；竞价history游标独立；9快照全部过期/未来/非法0HTTP，新epoch恢复；旧API/竞价发送状态字节对照。全store合同fixture按真实请求身份补10接口，217→227；不降低既有业务断言。

公共冲突接点仅registry新块/PLANNERS、pipeline import/_planning_inputs新族/normalize/identifiers/prereq/validation/run发送前约束、store新族字典/可选身份/日期、mirror复制名单。父可与其他候选串行合并；无publish/tick配置区改动。

Python3.10全套 `python -m unittest discover -s scripts -p 'test_tushare*.py'`：705 tests / 35.993s / OK，日志 `/tmp/tushare-realtime-runtime-full310.log`；专项9tests与Ruff通过。微基准输出是既有测试证据，不推断生产提速。
