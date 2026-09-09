# Tushare 接入线A：薪酬已观察报告期补采候选
- remaining_markets，Mac独立worktree quantmind-tushare-rewards-observed-periods；branch codex/tushare-rewards-observed-periods；commit 96148d269d060e4025a3f5250a1c505878352b42 已push，worktree clean。代码base4446d36，分支parent2a6e462只多协调记录。
- 6文件：stock_context纯合同/planner，registry仅stock_context依赖映射，pipeline仅identifiers中end_date投影/本API实际pair集合（9行），专属新tests/doc，旧stock_context测试依赖集合一处更新。无init/next_job/tick/publish/缓存/通用游标修改。
- 当前离线分母236具名/227注册、9未注册保留原分类与阻塞；28旧disabled记录中idx_anns、tdx_member/kpl_concept_cons有更晚启用coord，不能报实时禁用。完整审计源 /tmp/tushare-line-a-scope-4446d36.json、/tmp/tushare-line-a-disabled-evidence-4446d36.json；官方194原HTML SHA f640e1ef...6256bef19。
- runtime增量：只从stk_rewards jobs∪attempts原文发现code/end_date，保留历史/T/饱和与旧attempt。code-only继续，最大已见期近期刷新，全部实际合法pairs历史稳定补采；坏期间计gap，不猜季度/ann/range/offset或code×period全集。未创建父子完备分片、未改饱和父state/旧jobs/数据。
- 测试：新增7、全Python3.10 Tushare817项/41.853秒通过；Ruff/diff check通过。日志 /tmp/rewards-observed-full310.log。新较早期间在有限冻结历史后续轮补入、任务幂等、原文7列+未知/null→Parquet→reader、ann/end轴和其他family指纹均验证。
- 下一步：父仅pick96148d2审查后另定发布/启用；纯候选无生产/API/Token访问、配置/DB/队列修改或重启。仅已观察期间不等于全集，原1000未验证cap、1428旧响应、旧期修订与PIT gap保留；RRG仍blocked_data。
