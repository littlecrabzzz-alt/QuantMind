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
3. 严格接受原始合法股票源标识（含 T/历史股票）和合法 YYYYMMDD；不剥离 T，不改成季度末，不修补坏日期。无效/缺失的期间身份保留原文及 prerequisite 计数，合法期间继续规划。股票源命名空间本身失配仍遵循既有家族校验，不通过过滤坏股票来伪造有效全集。有效但不常见的日期也不擅自丢弃；它必须来自实际来源。
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
