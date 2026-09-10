# 接入线 A：管理层薪酬的已观察报告期补采

代码审计基线 `4446d36`；建立分支时 `origin/master` 已追加仅协调记录的 `2a6e462`，运行代码不变。仅离线读取仓库、既有官方 HTML 和交接记录，没有查询上游、读取 Token 或核查当前生产配置。本候选未部署、未启用、未写正式队列。

## 当前范围差集及本批选择

复用 `python scripts/audit_tushare_scope_gaps.py --output /tmp/tushare-line-a-scope-4446d36.json`，结果仍为 **263 基线页 + 13 发现页、236 具名 API、227 已注册可读、9 未注册**。六个财务 reader 别名不增加源 API 分母；42 无名页和未决提及仍保留。[原冻结差集](tushare-scope-gap-2abcd7f.md) 及对应完整 JSON 保持不变。

| 未注册接口 | 边界与下一证据 |
| --- | --- |
| `moneyflow_hsgt`、`ggt_daily` | 旧默认样本分别有 1 行（20260904）和 1000 行（20220526–20260907，has_more=true）；完整官方页失效，不能推完整字段或合法续页 |
| `ggt_top10`、`ggt_monthly` | 旧空参请求返回 API 参数/接口错误；需有效官方名称、必填输入、隐藏输出及历史口径，不能据此判永久停更或拒权 |
| `p_list`、`p_get` | 私有组合只读纯合同已有；不是公共行情，公共 reader 权限隔离未完成，不纳入本批 |
| `p_save`、`p_delete` | 写操作，不自动执行 |
| `pro_bar` | SDK 聚合入口，不能伪造同名 HTTP API；派生/复权和底层来源仍有对账义务 |

未接入不只表现为注册差集。台账有 **28 个显式 enabled=false 的历史观察**；其中 `idx_anns` 和 `tdx_member/kpl_concept_cons` 已有较晚协调记录说明分别以 calendar_extra/market_members scope 启用，不能把旧标签当当前状态。本轮没有读取 live config，以下是证据截至基线时的剩余事项：

| 注册但仍有启用/样本缺口 | 已记录范围及限制 |
| --- | --- |
| **`stk_rewards`（本批）** | 000001.SZ 全期 1428 行触本地保护，单期 20251231 返回 22 行且云/Mac全列一致；未自动启用，报告期全集未知 |
| `stk_high_shock`、`stk_alert` | 20260904、20260311 及对应窄范围样本为空；不是无权限证据，非空字段/过滤未验 |
| `eco_cal` | 20260904 日/范围各50行；20260910 bulk各100行满额，实际三country补样62来源行；国家/类别语义和 bulk全集未解 |
| `bc_otcqt` | 20260904 bulk2000触保护；同日范围控制返回09/07–09/09记录，日期过滤不通过 |
| `stk_mins` | 20260901 一日241行；秒窗控制曾限频，后续40203明确2次/天；不能据单样本自动启动全股票分钟历史 |
| `stk_premarket`、`stk_auction_o`、`stk_auction_c` | 20260904 请求拒权；不能继承另一个竞价接口权益 |
| `etf_mins/idx_mins/sw_mins/ft_mins/opt_mins/hk_mins` | 已记录20260908窗口（HK为20260904）拒权，保持独立分钟权限缺口 |
| HK 四财报、US 四财报 | HK 20241231报告期、US 20250401–20250430范围拒权；八接口分别保留，不能拿积分断言授权 |
| `yc_cb`、`factor_list` | YC 20260904 type0/1拒权；factor_list目录拒权，不能推断已启用的code-only factor_value不可用 |
| 实时十接口 | 已注册但未执行新有限 probe，默认关闭；仅 `stk_auction` 有合法历史，其余 snapshot/replay不可扩成任意历史 |

以上不是所有历史已取全的反向证明。已启用接口的未知起点、空窗、字段、附件、修订/PIT及饱和父分区继续属于完整目标。详细台账快照另存本次 `/tmp/tushare-line-a-disabled-evidence-4446d36.json`，不覆盖共享全局台账。

## 官方依据与最小改动

[官方194](https://tushare.pro/document/2?doc_id=194) 归档 HTML SHA：`f640e1ef2120aab9af52459fa460e9cbdbd34bae02bd473c9abdb9e6256bef19`，与原纯合同一致。必填 `ts_code`，可选 `end_date` 是**报告期**；没有公告范围、start_date、offset 或公开完整期间清单。七个已知输出均默认 Y：ts_code、ann_date、end_date、name、title、reward（元）、hold_vol（股）。未知列/null和来源行仍完整保存，未来隐藏字段不得按此冻结推断。

现有 planner 对薪酬只重复 code-only 请求，无法利用合法单期过滤。本候选复用当前 stock_context 家族、惰性规划器、固定 reader 和家族游标，补上：

1. `identifiers()` 从已有 **jobs ∪ attempts** 的 `stk_rewards` 原文抽取 code/end_date 对，包含被后续 job 结果替代的老观察和饱和观察。只按来源对去重，不从其他财报的 end_date 推断薪酬期间，也不把公告日期替换进去。
2. code-only 发现保持，每个股票的**最大已见报告期**与其轮流刷新；所有合法已见 code/period 产生 `epoch=history` 的稳定补采任务。没有已见期间时仍只发现，不猜季度、年份或股票×期间笛卡尔积。
3. 严格接受原始合法股票源标识（含 T/历史股票）和合法 YYYYMMDD；不剥离 T，不改成季度末，不修补坏日期。无效/缺失的期间身份保留原文及 prerequisite 计数，合法期间继续规划。初版股票源命名空间失配会阻断整个家族；下述 2026-09-10 修复将此收窄为有记录的叶级缺口，不宣称过滤后的股票为完整全集。有效但不常见的日期也不擅自丢弃；它必须来自实际来源。
4. 新发现只影响选择了 `stk_rewards` 的 stock_context 依赖。已启用的管理层/九转/AH三项以及其他 family 的政策/发现指纹不变；历史推进继续使用现有冻结快照，新增较早期间在后续生成轮补入，不重排正在扫描的历史尾部。

运行标识依赖新增 `stock_context_reward_periods`，映射纯 planner 的 `reward_periods`；不改配置键、表结构、镜像格式或 store 自然键。模块原本已在安装名单中，无需新镜像模块。默认关闭规则不变，只有实际选择 `stock_context_apis` 中的 `stk_rewards` 才会规划。

## 不解除的缺口与运行风险

- 1428是既有响应行数，1000是未验证本地保护值；本候选不提高它，也不声称供应商实际限额为1000/1428。
- 期间补采**不是**原父请求的完备分片证明，不创建 parent-child 完整关系，不修改父状态或旧请求/尝试。父请求或单期触界继续保留质量/完整性缺口。
- 只查询已见期间不能发现所有曾存在但被截掉的期间。code-only发现持续，仍不足以证明期间全集。最大已见期之外的旧期修订不保证持续刷新；原文新观察和已有 revision/PIT gap仍保留。
- 规划记录按实际期间数量增长，不能把新增请求数当真实提速或全量 ETA。父后续若选择启用，需要新的准确 API 范围和有限计划预算审计；不要重置已有未完成游标，也不要为本候选暂停当前采集。
- ann_date 仍是默认查询轴，end_date 只用于显式报告期 cohort；系统 observed/as_of 不等于历史供应商可见时间。RRG 仍 blocked_data。

## 验证

`PYTHONPATH=scripts:. python -m unittest test_tushare_rewards_observed_periods test_tushare_stock_context_contracts test_tushare_stock_context_pipeline`

新增7项覆盖合法实际配对/T/闰日/非常规期间、坏期间gap、缺发现保留code-only、其他family指纹不变、老attempts不丢、完整原文→Parquet→固定reader及ann_date/end_date区别、父饱和状态不变、有限历史扫描中新较早期间最终补入与稳定任务幂等。全部使用临时数据和 MockTransport，禁止socket/DNS/secret getter；没有生产读取或真实请求。旧运行测试只更新新增显式依赖集合的一处断言，业务检查保持。

本候选最终验证：Python3.10全 `test_tushare*.py` 共817项/41.853秒通过，Ruff和diff check通过；日志 `/tmp/rewards-observed-full310.log`。这些隔离结果不代表生产权限或下载已经完成。


## 2026-09-10：不让异常来源标识阻断合法薪酬补采

修复基线 `0c18fb2`。经现有云端业务入口只读 SQLite（`mode=ro`、schema 6）与来源对象 SHA 校验，839 个不同来源、2.323 秒内找到首个异常：`stk_managers` 原文的 `X20720.SZ`，对象 SHA `729eed0e7a6b5dae2e9a723d23c6a3a9f9ceffd9e3fd4b8050f50d77d67ff378`，观察 `6b6ea82158db46638a866fe8614da3b7.json`。它不符合既有 `T?[0-9]{6}\.(SH|SZ|BJ)` 股票源标识规则；不猜其实际证券类型或修成数字代码。调查在首个发现后停止，不能用它推全库只有一个异常。只读报告 `/tmp/stock-context-source-readonly-result.json`，没有初始化生产 Pipeline、访问 Token 或发上游请求。

最小修复只在 stock_context 的薪酬规划入口逐叶复用原校验器。合法股票继续 code-only 发现，合法已观察代码／报告期继续近期与历史规划；原始 discovery 和来源对象不变。异常产生独立能力记录 `planning:stock_context:stk_rewards:malformed_stock_supplier_identifiers`，包含非法数量、合法股票数及最多五个类型／SHA 摘要，仅短代码形状允许显示源值；任意非代码文本不会写入摘要。该记录为 `coverage_unverified`，即使父级恢复为 `validation_passed`，股票全集和异常标识仍未解决。

容器／配置错误仍阻断该家族；共享 `_stocks` 和其他家族的严格校验不变。没有更改合同元数据、发现依赖、规划签名、表结构或游标，已有冻结发现仍可继续使用。没有清除旧任务、创建虚假父子完成关系或解除原饱和缺口。

专项离线回归以等价的 **54 个合成来源配对**复现混合异常列表，验证实际 `identifiers()` → `plan_extended()` 有界推进、全部配对入队、旧阻断恢复、异常能力记录、原对象 SHA／父任务保持及重复规划幂等。这不是对生产 54 对的逐项重新执行，也不是上游全集证明。另验证 T 代码、非法摘要数量上限、其他家族及容器仍严格；仅更新两个旧“坏叶阻断”断言以匹配新规则，保留容器失败隔离覆盖。

```sh
PYTHONPATH=scripts:. python -m unittest test_tushare_stock_context_invalid_identifiers test_tushare_stock_context_contracts test_tushare_stock_context_pipeline test_tushare_rewards_observed_periods
```

候选仅在隔离 worktree 测试；未部署或修改正式任务／配置，RRG 准入不变。

该修复候选 Python3.10 专项 25 项/0.687 秒通过；完整 `test_tushare*.py` 840 项/46.199 秒通过（既有 5 项跳过），日志 `/tmp/stock-context-invalid-full310.log`。Ruff 与 `git diff --check` 通过；这里只确认隔离回归。

## 2026-09-10：已观察期间的独立有限追加

02:15:07Z 只读精确两个规划行和白名单配置（0.0025秒）：`recent:stock_context` offset1000，近期前缀6317，剩5317；`history:stock_context` offset7317，总枚举21496，剩14179，其中管理层13079、九转1027、AH73。两者冻结的薪酬组合仍54；父同时核验实际已观察393、已计划54。按每轮500、间隔900秒且每轮完整推进，旧recent还需11轮、history还需29轮；history约7小时15分钟后才结束，再下一轮才能刷新。这是条件规划时间，不是下载ETA；调度相位、失败和时间预算会延后。只读元数据 `/tmp/rewards-frozen-progress-source.json` SHA `4d7020206e0264a6296cb149db83b94d73db3915488d283dd5d5539b492f5e30`，纯重算 `/tmp/rewards-frozen-progress-assessment.json`。

候选基线8193d14，复用既有 `APPEND_PLANNERS` 和版本JSON快照，新增内部规划行 `history:stock_rewards_periods`。它只含实际已观察合法 code/end_date，不复制股票全集；只在stock_context启用、明确选择stk_rewards且家族校验通过时执行，不引入新的配置开关或采集family。复用原纯planner及字段契约，只保留其history补采，任务仍属stock_context、priority55、epoch=history，与原规划路径生成完全相同的ID。

每轮最多 `min(plan_jobs_per_tick,500)` 次幂等入队尝试，沿用history扫描/时间预算。新发现不会打断未完成的有限快照；完成后再按最新发现刷新。已有期间任务不改，重启从SQLite offset继续，时间预算耗尽保留未完成状态。原stock_context recent/history照常推进、签名和游标不重置；code-only发现、原quality父与未知期间全集缺口保留。仅新增一个紧凑pair快照，未来大规模发现仍有有限轮次延迟和单次迭代的协作式时间边界，不能承诺秒级追平。

专项命令：`PYTHONPATH=scripts:. python -m unittest test_tushare_rewards_period_append test_tushare_stock_context_invalid_identifiers test_tushare_rewards_observed_periods test_tushare_stock_context_pipeline test_tushare_planning_progress test_tushare_history_budget test_tushare_member_append_scope`。Python3.10共53项/1.846秒通过；隔离临时SQLite、MockTransport，socket/DNS/secret getter禁用。覆盖原快照未完即可追加、持续新增不饥饿、进程重开、稳定身份与父任务保持、关闭/未选/校验失败0追加、500上限及时间预算恢复。候选未部署、未改生产配置或队列，没有上游请求。

该追加候选完整Python3.10 Tushare回归856项/42.721秒通过，`OK (skipped=5)`，日志 `/tmp/rewards-fast-append-full310.log`；Ruff与diff检查通过。

### 追加 scope 必须先提交

首轮生产规划在普通家族enqueue阶段触160秒软超时，末尾追加不能保证执行。基线4e4b58d的最小修复把内部stock_rewards_periods放在规划循环首位，其他PLANNERS/APPEND_PLANNERS的相对顺序完全不变。沿用原追加预算和独立checkpoint commit；不改初始化、来源发现、前置校验、配置、采集或发布。若在到达规划循环之前即超时，仍不能保证追加执行，本修复没有解决整个planning的160秒上界。

新增两项回退对照：恢复旧末尾顺序时两项均失败；新顺序验证其余家族顺序保持，以及后续普通家族模拟耗时161秒并抛错后，通过独立SQLite只读连接确认追加任务和offset已经提交，原recent/history游标逐字段不变。专项55项/1.626秒通过，日志 `/tmp/rewards-append-first-target310.log`；旧顺序复现 `/tmp/rewards-append-first-before310.log`。全部隔离，不操作生产。

优先级修复完整Python3.10回归865项/43.108秒通过，`OK (skipped=5)`，日志 `/tmp/rewards-append-first-full310.log`；Ruff与diff检查通过。
