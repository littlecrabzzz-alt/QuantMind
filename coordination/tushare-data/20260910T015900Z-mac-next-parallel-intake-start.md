# Tushare下一轮并行接入开始

- 时间/节点：2026-09-10 01:59 CST，Mac主集成；基线`master@4446d36`，GitHub/Mac/云端已在上一轮handoff对齐。正式数据继续只由云端`/data/tushare`维护，Mac只读固定release；未改生产配置、数据库、队列或服务。
- 当前可复现目录审计：官方冻结与发现台账共236个具名scope，227个运行时可读、9个未注册；输出`/tmp/tushare-scope-gaps-20260910.json` SHA `640bf8d88dfd934225a09e10d85546fa35b93c1cc33442f593d6e4fdcf9cbba1`。余9项为停止/替代待确认的旧互联互通读接口4、私有组合读接口2、明确排除的写接口2及SDK组合`pro_bar`1，不能为追求注册数虚构公共HTTP契约。
- 生产配置现有23个family开关中只有`foreign_financial=false`；其HK/US行情、复权与财务接口已有明确permission_denied证据。其余family继续近期与历史采集，500档分层门控、900秒规划/发布周期不变。云端采集与附件消费者均active。
- 并行A由remaining_markets审计未登记与已probe未enable范围，优先准备`stk_rewards`基于已观察真实`code+period`的补采候选，保留code-only发现、父分区饱和状态和上游完整性gap，不把观察期当全集；不操作生产。
- 并行B由structured_contracts诊断纯采集160秒soft-timeout。真实脱敏样本`/tmp/planning-cadence-live-samples.json` SHA `18a1eb9d728842808bcf76b2fcf7a6a9c401840beddc79036b1ed9f9a67655db`；重点核对饱和分片处理中是否重新扫描全部identifiers。候选不得提高资源、超时或请求预算，也不得丢弃任务、原始数据或历史义务。
- 并行C由text_contracts核对RRG`blocked_data`门槛，优先推进历史行业成员PIT、ETF映射/历史池和开盘交易语义；不得从当前成员或观察时间伪造`known_at`。能在固定版离线完成的先做，需要真实权限/样本的准备有界probe/verifier并留证。
- 主集成继续保护仓库中研究工作流的既有未提交文件，不暂存、不重置。候选分别在隔离worktree提交/push；root审查通过后才合并、生产排空/发布、真实小样本和Mac固定版闭环。
