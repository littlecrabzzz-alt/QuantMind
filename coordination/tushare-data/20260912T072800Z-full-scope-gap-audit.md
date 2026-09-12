# Tushare 全范围接入差距审计

- 时间、节点、任务标识：2026-09-12 07:28 UTC，Mac，`/root/queue_headroom_audit`
- 状态：完成，只读固定版审计
- 分支、worktree、提交：共享主工作树 `master`，审计时 HEAD `5c6af429bc65807117ff22913ecbb4fbcd010d90`；仅新增本记录及同名 JSON，未提交
- 分工：本任务只负责全范围差距与下一接入目标；未修改生产代码、registry、coverage ledger、progress、服务或数据
- 输入：`docs/tushare-integration-plan.md`、263 项 pinned catalog、coverage ledger、244 API registry、Mac 固定版 `data-ce43326...`

## 结论

263 只是 2026-09-08 的目录基线，不能作为范围上限。当前 ledger 已在该基线上另外记录 25 个发现页面和 3 个未决 API 名称；registry 有 244 个 API，其中固定版 ce43 的 coverage 已出现全部 244 个，但只有 194 个 API 有数据叶，50 个没有数据叶。固定版自身仍明确 `history_complete=false`、`historical_versions_complete=false`、`unimplemented_catalog_scope=true`、`rrg_status=blocked_data`。

真正尚未注册的读取接口只有 `p_list`、`p_get`。`p_save`、`p_delete` 是账户写入/删除动作，应继续排除；`balancesheet/cashflow/express/fina_indicator/forecast/income` 是对应 `*_vip` 采集接口的兼容展示名；`pro_bar` 是 SDK 派生封装；`ggt_monthly` 的官方页面/接口名仍无有效权威证据，不能从 `ggt_daily` 猜造。

50 个无数据叶接口中，34 个已有 runtime `permission_denied`。另有 `stk_alert` 仅 3 个空分区、`stk_high_shock` 仅 1 个空分区，既无数据叶也无 runtime denial；这两项不能归为权限拒绝。其余主要是已注册但默认关闭、未实际启用的发现接口，或停更/遗留接口。完整名单和分类在同名 JSON。

## 下一实际接入目标

建议先做 `stk_alert` + `stk_high_shock` 的两请求有界复核。两项代码和字段合同已存在，但 ce43 仍为零数据；官方当前页面分别给出 2026-03-11 和 2026-03-12 的非空示例，且都要求 6000 积分。当前 10100、已知 2000 积分 tranche 到期后预计 8100，均高于门槛，但实际账户权限仍须由真实响应证明。

最小验收顺序：对上述两个官方示例日期各请求一次；保存不可变 raw/attempt；核对返回日期与请求过滤语义、完整字段和 1000 行上限；只有非空且合同一致时才启用 exact-day 历史计划。成功样本不等于历史完整、修订完整或 PIT 可用。

## 后续优先级

1. `opt_daily`：1204451 pending、17 split pending，仅有 18 个数据叶且 capability 为 `empty_unverified`。先找到确定非空的期权/日期，再证明期权代码 fanout 与饱和处理。
2. `moneyflow_dc`：613875 pending、123 split pending，现有 `possibly_truncated`；按日期/股票合法拆分并从官方 2023-09-11 边界补齐。
3. `dc_member`：453389 pending、439 split pending；先闭合分裂后代和退市板块发现。其 `trade_date` 不能充当 historical `known_at`。
4. `index_daily`：143081 pending；继续 exact 批次，同时补供应商 cap 与最早历史合同。
5. `index_weight` + `ci_index_member`：前者 107701 pending、1259 split pending、91 blocked；后者已有 295 叶，但最早历史、修订、删除、cap 和 known_at 未证实。RRG PIT 继续 blocked。
6. `top10_holders` + `top10_floatholders`：合计 256235 pending；补公告日/全历史修订扫描，保留 distinct rows 和 `ann_date/end_date` 语义。
7. 九个已购文本接口：先修 `research_report` schema/319 quality、`anns_d` 1201 split pending、`major_news` 453 split pending，再闭合来源、历史和修订。独立权限有效至 2027-09-08。
8. `p_list` + `p_get`：实现默认关闭的只读账户快照合同；10100 积分和六项独立权限都不能证明其访问权。永不自动调用 `p_save/p_delete`。
9. 因子、分钟、实时、港美股权限族：已有拒绝的接口只在 entitlement 变化后复核；`factor_value` 的 712 个数据叶只证明观察到的试用/样本范围，不能据此推导完整独立权限。

## 证据与边界

审计没有打开 live SQLite，没有访问凭据、上游或服务。ce43 的 421257077 字节 manifest 只流式提取 dataset API、capability 和 coverage 字段，没有加载或重复 hash 129220 个数据叶；manifest SHA256 为 `ce43326f62bfc30dccb314a965c8e58533472f6914735e32692cdbec023f60e6`。本次机器差异见 `coordination/tushare-data/20260912T072800Z-full-scope-gap-audit.json`。

官方合同复核：[`index_weight`](https://tushare.pro/document/2?doc_id=96) 明确月度成分权重与 2000 积分；[`stk_high_shock`](https://tushare.pro/document/2?doc_id=452) 和 [`stk_alert`](https://tushare.pro/document/2?doc_id=453) 均明确单次 1000 条、按代码或日期循环、6000 积分。其它优先项的官方页面 URL 已逐项写入机器 JSON。

未验证项：固定版 ce43 是本次指定审计基线，并非声明云端此刻最新状态；没有执行真实权限复核；没有把 category 页面计作 API；没有把 fetch/observed 时间当历史 known_at。

下一步：由正常 Tushare 采集窗口先运行 `stk_alert`/`stk_high_shock` 两个官方样本日期的有界真实复核。若仍为空，保留为 `empty_unverified` 并转向 `opt_daily` 的确定非空范围；若非空，按现有风险事件合同生成小批 exact-day 计划并进入标准固定发布/离线验收。
