# RRG member PIT contract audit

- 时间、节点、任务标识：2026-09-11 01:13:58 UTC，Mac，`rrg_member_pit_audit`
- 状态：`blocked_data`；未创建成员 exact runner
- 基线：`master` at `16cf8b516c0d0c7758691fb3fb58bcd6a14bcaed`
- 范围：只读检查仓库 registry、catalog、合同、既有文档和 runner 模式；未读取生产 SQLite、凭据或固定数据，未调用上游，未触碰研究工作流未提交文件。

| 接口 | 可表达内容 | 不能表达的 RRG 准入证据 |
|---|---|---|
| `dc_member` | 东方财富板块在 `trade_date` 的 `ts_code/con_code/name` 快照；公开历史下界为 2024-12-20 | 不是中信一级分类；无公告/首次可得时间、版本号、修订或删除语义。抓取时间不能倒填为历史 `known_at`，DC 代码也没有版本化中信映射。 |
| `ci_index_member` | 中信 L1/L2/L3 与证券的 `in_date/out_date/is_new` 生效区间 | 无 `known_at` 或历史发布时间，无分类版本/修订标识；`is_new` 是当前过滤条件，不能重建当时可见版本。 |
| `index_classify` + `index_member_all` | 申万 2014/2021 分类及分级成员区间 | 分类体系不是中信；同样没有成员公告时间和历史发布版本，不能替代中信 RRG 输入。 |

仓库合同已经明确保留这些边界：`backend/shared/tushare_dc_extra_contracts.py` 将 `trade_date` 与 PIT 可得时间分开，并声明旧修订、删除和历史板块全集未证实；`backend/shared/tushare_rrg_contracts.py` 明确记录 `ci_index_member` 没有 `known_at`/历史发布时间。`docs/tushare-intake-runbook.md` 禁止把首次抓取时间倒填为历史 `known_at`。现有原始对象和 observation 可证明本次抓取来源与内容，却不能证明某历史信号日当时已经可得。

因此本次没有新增 `dc_member` 或 `ci_index_member` exact runner。增加吞吐只会扩大 raw coverage，不能满足当前目标的数据合同，并容易把“已采集”误读成“PIT 可用于 RRG”。解除阻塞至少需要中信一级分类和成员的版本化来源，包含 `effective_from/effective_to`、可验证的 `known_at`/发布日期、revision/vintage 标识、修订与撤回语义，以及历史分类全集和来源文件哈希；取得这类合同后再按现有 exact 模式固定 release/config/task/code 哈希并有界执行。
