# R01 策略、回测与前向虚拟账户

2026-09-26。本模块把 R01 接入现有策略管理、回测中心、交易页和监控。原研究脚本作为来源证据保存；正式执行使用发布版本里的 `on_signal(ctx)`，不由每个 agent 重写撮合、费用、分红、估值或风险账本。

## 对象与入口

```text
研究课题 ──来源──> strategy_storage 策略草稿
                     └─发布─> strategy_revisions 不可变版本
                                 ├─公共回测─> qlib_backtest_runs / 回测中心
                                 └─冻结─> R01VirtualRunConfig / 独立 r01vr 账户
                                                └─ReplayLedgerCheckpoint / 策略监控
```

版本绑定代码与 hash、参数、执行/风险配置、输入 manifest 与 SHA256SUMS、执行引擎指纹、研究课题、原始脚本全文及来源版本。改代码或执行引擎必须发布新版本；冻结后不得原地换逻辑。原始脚本下载按字节核对 SHA256，平台不依赖 agent 电脑上的原路径展示代码。

本地页面为 `http://127.0.0.1:13001`：

- 策略管理：`/#/user-center?tab=strategies&strategyId=61`，看版本、代码、来源文件、配置；运行/冻结/编辑发布新版本。
- 回测中心：`/#/backtest?strategyId=61`，真实运行历史、按日期账本、权益回撤、对比与按原版本复跑。
- 模拟交易：`/#/trading?paper=61` → 策略虚拟账户，读真实配置、Redis 状态和 PG checkpoint。
- 首页策略监控：复用同一账户状态组件。历史回测收益不累计成虚拟盘收益。
- 研究工作台：问题、进展、结论、证据和上述对象链接；工程验收在可恢复的独立归档分类中，原事件和附件保留。

## Agent 的统一执行接口

均为已有 JWT 认证的 `/api/v1` API。通过浏览器代理或 Engine；勿把令牌写进命令参数、报告、代码和仓库。

| 操作 | 接口 |
|---|---|
| 保存策略草稿 | 既有 `POST /strategies`、`PUT /strategies/{id}` |
| 发布不可变版本 | `POST /strategies/{id}/revisions` |
| 版本列表/全文 | `GET /strategies/{id}/revisions[/{revision_id}]` |
| 原件下载 | `GET /strategies/{id}/revisions/{revision_id}/source/{name}` |
| 运行与复跑 | `POST /strategies/{id}/backtests` |
| 查询历史/结果/对比 | 既有 `/qlib/history/me`、`/qlib/results/{id}`、`/qlib/compare/{id1}/{id2}` |
| 冻结为独立虚拟账户 | `POST /strategies/{id}/paper-runs` |
| 真实账户状态 | `GET /strategy-paper-runs` |
| 停止/恢复/归档 | `POST /strategy-paper-runs/{id}/control` |
| 研究/工程分类 | `GET /research-catalog`、`POST /research-catalog/{id}/category` |

发布字段见 `routers/r01_strategy.py:PublishRevision`；必须明确全部执行参数与源文件，禁止悄悄套默认成本。公共回测请求：

```json
{"revision_id":"<64位版本hash>","key":"<稳定请求键>","start_date":"2014-08-01","end_date":"2026-03-24"}
```

同键同配置返回同一记录，异内容冲突拒绝；复跑使用新键，并带 `rerun_of`，必须保留原版本、原日期。请求立即登记 pending，Celery 更新 running/completed/failed。终态结果不可因缓存一直停在 running。

策略只实现 `on_signal(ctx)`，返回 `{targets, reason, state?}`。`targets=null` 表示不调仓；权重映射中的缺项代表目标为零；权重非负且总和不超过 1。上下文含截止决策日的历史价格、月末标识、冻结参数、上一账本快照及显式状态。使用既有 AST 门控、限制指令数；禁止 import、IO 和私有属性。历史执行另在无数据库/认证/供应商凭证的资源受限子进程中进行。此沙盒用于本地受信策略，不作为任意敌对 Python 的强隔离承诺。

回测和持续虚拟账户共同调用 `evaluate_program`、`decision_context` 和 `R01Ledger`。手续费、整手、分红登记/应收/到账、估值陈旧、风险暂停与成交约束沿用公共实现。原始研究 runner 不直接导入为在线交易程序；公共适配与独立复算证据分别保存。

## 数据和前向执行时间

开发回测上限固定为 2026-03-24。2026-03-25 至 2026-09-24 保留段在 API 和执行入口拒绝访问，边界不自动滚动。R01X-A 已经看过全历史，不能重新宣称这半年是独立盲测；未来账户从冻结后的时间开始，是新的前向证据。保留段正式评估入口及准入另行处理，不绕过当前门控。

冻结账户须已有该版本完成的公共回测。这是工程前置条件，不等于研究结论独立验收。B1/B2/B3 当前登记为待研究准入的适配版本，未替研究组宣布通过或启动虚拟账户。

当前账户采用 `post_close_next_open_accounting`：

1. 决策日 16:15 起，用已发布数据生成决策，最迟须在次开市日 09:25 前冻结；超时记 missed，不用事后行情补造决策。
2. 次开市日开盘价是虚拟成交假设。只有该日日线完整到达后，从 15:45 起记账，补记窗口至次日 09:15。它不是早盘实时撮合。
3. 隔夜补记完成后才继续依赖它的决策。缺数据、未知日历与错误保留为受阻/等待状态，不推进虚假的成功时间。
4. 每日输入从 Mac 只读来源档案构建不可变增量包；输入缺口最多自动补 10 个交易日，超出则显式受阻。已有日包不可覆盖，修订需另行发布。
5. 交易日历每日一次经已有供应商采集接口获取，原响应/hash/观察时间单独留证，可含未来休市安排，不含未来价格。调度先执行待记账决策再生成新决策。

停止经过 requested → received → effective；恢复沿用原账户和 checkpoint。只有停止已生效可归档，归档不删除账本。风险暂停仍要求显式恢复。心跳陈旧不等于运行成功。

## 本地运行

在 integration worktree 运行：

```sh
python3 scripts/start_r01_platform_candidate.py --frontend-port 13001
```

脚本复用 `quantmind-dev` 的沙盒配置和同一 PG/Redis，创建正常 Engine、专用队列 worker、beat；不是另写一套研究执行服务。Engine 监听 loopback 18083，前端代理策略/回测/虚拟账户/目录 API 到它。其余请求沿用主服务 8000 和已冻结 H1 接入；H1 身份与 readiness 不改写。

自有容器为 `r01-platform-engine`、`r01-platform-worker`、`r01-platform-beat`。worker 并发 2，使日包构建不独占运行槽；每个子进程处理一项任务后退出。beat 仅派 R01 专用任务：5 分钟检查调度，30 分钟检查输入。`ENABLE_REAL_TRADING=false`，只执行 platform 账户，原研究与其他队列不接管。

脚本不会替换已存在容器或占用端口的进程。代码更新后按任务状态重启自有服务；修改启动参数需停止空闲的自有容器后重建。PG、checkpoint、包、原件不删除。原件/运行数据在主沙盒 `HOST_RUNTIME_PATH/data`；输入 registry 在 `data/r01-platform/registry.json`。密钥仅经内存和自动清理的 0600 临时环境文件传递。

Mac/Docker/前端在线是运行条件；未配置 macOS 开机启动前端。新代码在独立 worktree，尚未合入主分支或发布云端。停用时先从页面请求停止并等生效，再停止专用 beat/worker；不要停主服务、共享数据库或冻结 H1 服务。

## 验证

```sh
python3 -m pytest backend/services/tests/test_r01_platform_execution.py backend/services/tests/test_r01_virtual_run_pipeline.py backend/services/tests/test_r01_virtual_run_scheduler.py backend/services/tests/test_r01_virtual_run_fixes.py -q --no-cov
docker exec r01-platform-engine python -m unittest backend.services.tests.test_r01_platform_comparison
node node_modules/typescript/bin/tsc --noEmit -p electron/tsconfig.json
# 在 electron/ 下执行
node ../node_modules/vite/bin/vite.js build
```

测试涵盖相同信号/逐日 NAV、恢复与重复执行、截止时间、隔夜补账、日历扩展与篡改、跨版本拒绝、身份校验。实际 API 与页面验收见 `handover/platform-integration/REPORT.md`。这些是本次工程交付验证，不替代研究独立验收、长期虚拟观察或真实交易授权。
