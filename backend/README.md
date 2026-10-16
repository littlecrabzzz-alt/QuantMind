# 后端开发入口

QuantMind 的业务边界保留为四个 FastAPI 服务；当前仓库 `docker-compose.yml` 的 OSS 部署把它们运行在同一个 `quantmind` 容器内，不是四个独立容器。

| 服务 | 默认端口 | 应用入口 | 负责范围 |
|---|---|---|---|
| API | 8000 | `services/api/main.py` | 认证、用户、管理与服务代理 |
| Engine | 8001 | `services/engine/main.py` | 策略生成、回测、模型推理、投研计算 |
| Trade | 8002 | `services/trade/main.py` | 订单、成交、账户、模拟撮合与交易控制面 |
| Stream | 8003 | `services/stream/main.py` | 行情 REST 与 WebSocket 推送 |

端口表是代码默认值，不是服务正在运行的证明；本地开发源收敛不代表数据库或服务已迁移。

## 启动与配置

部署、环境准备和数据目录从[根 README](../README.md)进入。`main_oss.py` 根据 `SERVICE_MODE=all/api/engine/trade/stream` 调度上述服务，端口可由 `API_PORT/ENGINE_PORT/TRADE_PORT/STREAM_PORT` 覆盖。

`main_oss.main()` 在启动服务前执行 schema 初始化、管理员播种和内置股票池准备，可能写数据库与成员文件；不要把运行它当只读检查。单独启动 `services/*/main.py` 与走 OSS 启动器的初始化行为不同。

- 配置来源由 `shared/config/` 及部署注入环境决定；不要在服务子目录另维护一套数据库凭据。
- 普通客户端先访问 API 网关，由其转发鉴权上下文；内部调用密钥不得下发桌面端。
- 保持 `shared/` 为跨服务公共能力；不要通过导入另一服务的私有实现绕过边界。
- 运行态与资产归属以实际配置、数据库和挂载为准，不沿用旧 GKE 参数表或历史验收结论。

## 领域合同与排障入口

- [Qlib 回测](services/engine/qlib_app/README.md)：异步任务、策略存储和结果查询。
- [模型推理](services/engine/inference/README.md)：模型选择、数据日与信号生效日。
- [因子挖掘集成](services/engine/rd_agent/README.md)：RDLoop、市场适配与运行资源。
- [股票池](shared/stock_pool/README.md)：成员事实源、引用语法和空池语义。
- [ashare-lab 桥接](shared/ashare_lab_bridge/README.md)：次日开盘撮合与适用条件。
- [WebSocket 协议](services/stream/ws_core/README.md)：握手、订阅和心跳。
- [最小联通检查](DOCS/backend_smoke_checklist.md)：只用于已配置实例，不代替业务回归。

AI-IDE 的 `services/engine/routers/ai_ide/skill_templates/*.md` 由 `skill_engine.py` 加载为运行时模型指令，不是普通开发说明；修改时应按提示模板合同评审并随运行包保留。

## 冻结 ashare 纸面观察

运行时只复用 `vendor/ashare-lab/src/ashare_lab` 的原引擎，不走实盘 Broker、
不创建第二个协调器，也不把余额镜像到 Redis。登记统一走
`shared/strategy_storage.py`；每日命令与已认证 API 读取同一持久目录
`output/ashare-paper/<owner_hash>`。`owner_hash` 是排序、紧凑 JSON
`{user_id,tenant_id}` 的 SHA256；`ASHARE_PAPER_ROOT`、CLI `--ledger-root`
都配置基目录，由入口追加同一 owner_hash。管理员没有跨用户/租户读取豁免。

固定八户为 `lowvol`、`b2_lowvol_vt`、`b3_lqv_buf_vt`、`i7_turn_of_month`、
`s1_invvol_etf`、`cb_double_low`、`cta_combined`、`cta_trend`。S1 初始资金
1000 万，其余各 100 万；均为 DRAFT/OBSERVATION、冻结参数、无交易权限，
不改变原研究不通过、事后选择或 ETF/指数版适用边界。
原三户迁移 `ashare-takeover/trees/ashare-lab-paper/paper` 的 meta/四个 CSV
原字节和创建时间；原始 10/13 NAV/待成交信号，原创建时间原样保留。
10/13 不代表开户日；[文档勘误记录](../output/platform-delivery-20261016t194641290902z/documentation-erratum-7258.json)
同时说明已冻结部署文档的历史口径，冻结 snapshot 不改、不重部署。其余五户记录命令实际开户 UTC，
历史起点只是 replay_start。缺源时不写零 NAV；真实引擎无信号/无成交的 cash-only
是合法结果。成交数值列显式转换 float 后检查有限性，NaN/Inf 仍拒绝追加。

B2/B3 的原 `VolTarget` 描述固定为 `target_vol/window/step/max_exposure/base`；
新工厂显式锁定中性扩展 `cut_delay=0,cut_scale=1,downside=False`，仍使用当日 raw
仓位、原对称样本标准差 `np.std(ddof=1) * sqrt(252)` 和原 step floor。
仅这三个精确中性扩展可使用原描述；非中性值、未知新增字段以及原四数值或递归
base 描述变化一律拒绝。`init_account` 整体 meta 严格比较不放宽，原 meta 字节不改。

可选 AI 选股客户端只在实际使用时读取/验证真实 LLM 配置；未配置密钥不阻断
Engine 路由导入及非 LLM 健康/纸盘服务，不注入模拟密钥。OSS 启动播种先复用
`ProfileService._ensure_profile_table` 完成既有 profile 可空列迁移，再查询 profile。

### 唯一日更契约：paper-readiness v1

唯一 source QA 发布 `paper-readiness.json`；tick 不采集、不重判数据可用性，
不按所有接口日期取最小值，也不按 mtime/weekday 推断交易日。
`accounts[name].state` 是逐户 ready/pending/blocked 判定，顶层 ready 不等于八户全准入。

仅有两个数据路径根：`--archive-root=/data/tushare`（受管行情/PIT/真实日历），
`--artifact-root=/app/output`（归档及补源资产）。所有输入 path/manifest_path 必须为
相应根下的相对路径；禁止绝对路径、逃逸 `..`/符号链接及可写 ashare-paper 作为输入。
QA 只读挂载 `/run/quantmind-market-source/paper-readiness.json`，宿主产物位于
`~/Library/Application Support/QuantMind/market-source/paper-readiness.json`；
QA 入口不是第三个数据根，纸盘基目录独立可写。

| 字段 | v1 合同 |
| --- | --- |
| `schema_version,state,checked_at` | 整数 1；ready/pending/blocked；aware UTC/Z 审计时间 |
| `usable_date,reasons,per_api_cutoffs` | 真实共同行情闭市日；原因数组；按各接口真实日期轴核验的截止日，无时间轴维度表可为 null |
| `market` | `pointer_path,release_id,manifest_path,manifest_sha256`，指针与 manifest 字节身份必须一致 |
| `fundamentals` | managed 同 market；pinned 必须 `pointer_path:null`、固定 `manifest_path/manifest_sha256`、非空 release_id 或 data_id、as_of 与 lag_note，不冒充已追新 |
| `calendar` | `path,sha256,confirmed_next_session`；真实 SSE 行且确认下一开市日 |
| `accounts` | 必须且仅有八个授权名称，逐项 `state,reasons`；I7 另有 calendar_context |
| `asset_inputs` | 必须且仅有 I7、S1、CB、CTA combined/trend 五个账户键；逐项 `state,reasons,path,version,manifest_path,manifest_sha256`，不是 cb/futures aggregate 别名 |
| `asset_bundle` | 已核验 canonical 的 `pointer_path,schema_version,data_identity,bundle_path,bundle_sha256`，未绑定为 null |

五资产唯一入口为 `ashare-input-supplements/CURRENT.json`：
`schema_version=1,data_identity,bundle_path,bundle_sha256`，bundle 固定在
`ashare-input-supplements/assets-<data_identity>/bundle.json`。tick 对照 QA、当前指针、
bundle 字节与五项资产身份；缺失/旧 schema/漂移均 pending，不扫描 epoch、不读旧
seed fallback。准备后再次核同一身份和逐户判定，变化时保留 prepared 而不追加。
稳定 prepared identity 含行情/PIT、usable_date、日历、canonical 五字段、五项资产及
冻结规则哈希；排除 checked_at、临时 QA 文件 SHA、state/reasons/lag_note。
inputs.json 封存后只校验复用，不覆写；tick.json 保留实际 UTC、上海时间、due/reason。

I7 `calendar_context` 包含 `exchange,replay_start,usable_date,calendar_through,`
`required_month_end,next_month_first_session,next_two_sessions,complete,state,reason,calendar_sha256`。
从 replay_start 所在月首到 usable_date 所在月末必须逐自然日有唯一真实 is_open=0/1，
下一月首到首个开市日同样完整，usable_date 后至少两个真实开市日供 i+2 使用。
单独 confirmed_next_session 或只到月中均不足，不足仅 I7 pending，不改 TOM 策略。
股票、CTA warmup、CB 年龄、I7 共享同一真实合并日历，不能各挑不兼容片段。

ETF 输入为真实归一 `date,code,open,close,adj,amount,volume,up_limit,down_limit`
Parquet，元/份单位，包含 510300.SH/511010.SH/518880.SH；不猜 ±10% 涨跌停。
I7 沿用 calendar_nav 每边总成本 0.075%，不捏造拆分；S1 模型
`s1-etf-secondary-fees-v2` 的 ETF 卖出印花税/股票过户费为零，其余冻结模拟成本不改。
`shares *= adj_ratio` 只是复权再投资/份额 proxy，不是现金分红账本；
实际持有 ETF 遇非 1/缺失因子比或已知真实 fund_div 除息事件时追加前 blocked，
不凭因子造现金或新股，未观察到事件不代表现金分红历史完整核验。
原引擎 positions 是稀疏表，从未持有的 ETF 没有列；分红 guard 仅将这种隐含零数量
重索引为零，不给价格、复权或日历缺失填零，也不跳过 I7。真实 510300 回归覆盖
现金期与跨月买卖；原 `calendar_nav` 参考曲线和整手引擎成交/NAV 各按原公式核对，
不把 fractional 参考指数冒充真实整手账本。

CB 复用 cb_basic/cb_call/cb_daily、真实生命周期和 cb_over_rate；万元成交额转元，
周末最低 20 券信号、次日开盘、10 张一手、每边佣金 0.02%/滑点 0.1%/无印花税。
CTA 保留原 45 商品品种、完整 250-return warmup/held/replay/carry 闭包、真实 settle，
只消费有源对象/公式证据的 `normalized_multiplier`；原 fut_basic.multiplier 对商品为
NULL 是合法状态，不是补齐目标。按 `per_unit × trade_unit尺度 ÷ quote_unit分母尺度`
换算；JD 5 吨/每 500 千克报价为 10，不复制 5、不拿 CFFEX 替代。
每周最后实际交易日信号、次日收盘执行，逐日结算盯市/移仓两腿各 0.02%；
不建模保证金、抵押品收益和强平，不提供交易许可。

### 原始信号、持久化和验收入口

原三户 t13 空 targets/trades CSV 不等于没有 pending 信号。迁移先以独立子进程
运行归档 paper/forward 源码和原数据/两年 warmup，对照原 latest.md 50 个两位百分比
目标，再与当前 runtime 全精度逐股比较（rtol/atol=1e-12），不调权重“过关”。
实际 `run`/`tick` 在追加 10/14 前强制封存 inception_source、signals 及逐股
inception_reconciliation 证据；缺证明的旧迁移账本拒绝自动追认。

```bash
python scripts/ashare_paper_daily.py reconcile-inception \
  --source-ledgers output/ashare-takeover/trees/ashare-lab-paper/paper \
  --manifest "$PAPER_INPUT_MANIFEST" --out "$NEW_INCEPTION_EVIDENCE"
```

输出必须为新文件；成功 0、不符 1。省略 manifest 仅做原冻结输入上的源码 parity。
`run --manifest` 是显式不可变回放，不是循环日更；生产用 `tick`。
`install-launchd --container quantmind-local-quantmind --docker-executable ...`
只渲染现有 paper plist，部署负责人负责安装/激活。使用 StartInterval=900，
不改全机 TZ、不 mock 时钟；tick 显式 Asia/Shanghai，真实 SSE 当日 18 点后才 due，
过去已闭市日可在周末/盘前/唤醒后 catch-up。缺日历 pending、未闭市 not_due。
退出 0 为已应用/对齐或明确 not_due，75 pending/partial，1 blocked；
not_due 不证明已完成日更。延迟和首次补跑都标 replay；只有当日及时、开户与前一状态/
信号均事先持久化才标 forward_paper_observation，不重跑追认为前向。

所有写入共用文件锁，先比较完整历史前缀再构造增量，payload/pending.json 事务
只接受旧/新哈希恢复；代码、参数、输入、现金/NAV/持仓/成交/费用/目标/信号前缀漂移
拒绝写入。API 只读不恢复事务：`GET /api/v1/simulation/frozen-paper/accounts`，
模拟交易“冻结纸面观察”页显示同一八户账本及精确阻断原因，不造余额。
读取先校验原生身份，再在线程中以非阻塞共享锁获取已封存快照；日更持有独占锁时，
立即返回 HTTP 409、`detail.state=updating`，不读取半提交财务、不延长代理超时或重试。
页面明确显示更新中并保留同作用域上次成功读取的真实财务；首次尚无快照时不填零。
其它服务请求不等待账本锁；写入结束后手动刷新仍按原 seal/身份检查读取。
CLI/native async run/API 均通过 strategy_storage 校验真实 owner/tenant、strategy ID、
frozen_source_id、runtime_code_sha256 和 strategy_code_sha256。
源码选择的 assembly hash 不等于实际扩展后的运行时代码哈希。

验收必须同时保留真实原始 pending 逐股对账、八户财务前缀/重复零新增、
实际 native async run/CLI/生成 plist 命令、已认证页面、owner/tenant 隔离及重启持久性。
source QA green、单元测试、静态构建和只渲染 plist 都不能代替这些运行证据。
统一回归入口为 vendor 的 test_frozen_paper/test_paper_tick/test_paper、
backend/tests/trade 的权限/CLI 测试；前端 typecheck 由集成负责人在全部变更后统一执行。
