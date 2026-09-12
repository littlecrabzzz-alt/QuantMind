# Tushare identifier discovery small-key candidate

- 时间、节点、任务标识：2026-09-12T07:43:47Z，Mac，`/root/financial_next_batch`
- 状态：进行中
- 分支、worktree、提交：计划从 `d61e93d6` 建立 `codex/tushare-discovery-small-keys`，worktree `/private/tmp/quantmind-discovery-small-keys`
- 分工：仅负责 `backend/shared/tushare_pipeline.py` 与 identifier discovery 专项测试；根任务负责镜像、生产证据、集成和部署。

本次候选只优化 `Pipeline.identifiers()` 的全量证据遍历，保留 jobs/attempts、历史尝试、请求敏感 observation、对象缺失或替换时 fail closed 的合同。不引入 schema、持久缓存、并发、凭据或生产数据访问。

验证将比较旧/新完整 `Pipeline.identifiers()` 的规范化输出，并在固定有限夹具上测量完整调用；若语义或物理证据检查不能保持，或没有可观察收益，则拒绝候选而不削弱合同。
