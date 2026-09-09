# Structured 消费公平候选交接

Mac 隔离 codex/tushare-text；基线8c2e938，候选0cce3a7。所有权释放：pipeline仅__init__/next_job/邻接helper；3个既有测试仅schema断言5→6；新专项测试/短doc。不改规划、队列内容、publish或其他family逻辑，不生产操作。

实际pending API索引seek循环；各API独立3近期:1历史机会，空桶借用，冷却跳过，跨组fallback真实落structured同样公平；失败也计次，checkpoint/gates/family_turn同事务，commit失败回滚。unknown API按既有合同回退仍可选，缺/非法api_name明确错误保留。旧无rpm入口保留不建gate语义，只在structured执行相同轮转。

53项相关tests通过（8.19s），ruff与diff check通过；53含新12项以及v5索引、extended、partition closure、pipeline回归。临时400k pending迁移243.1ms，索引11,210,752B（10.7MiB）；全部job含rowid迁移前后SHA c97fd422438bd0cc6da8dff62678d1e89241ab6d7943f3b22e946bd87cbc59d5一致。seek23/桶48 VM、无temp sort，52次helper+checkpoint0.97ms/17700VM；都是合成最优输入，未声称生产最坏时延。

证据：/tmp/tushare-structured-fairness-regression-20260909.log SHA256 fdd243ba57fb308d63fe3eecbea223bb0b8f13ef921ae0f7b4f1ac3738f95e56

部署边界详见 docs/tushare-structured-fairness.md：父维护窗口内SQLite backup一致备份；schema6仅新表达式索引，原job/planning/offset/status全保留；旧runtime拒绝6，不可拿旧DB覆盖升级后新增进度，不可只降PRAGMA。父决定合批部署。大量逐job retry_after未到期可能仍扫描多候选；外组fallback/最早冷却查询保持原实现。公平保证已入队history机会，不解决尚未枚举daily_basic的planner前序延迟，不縮历史范围。
