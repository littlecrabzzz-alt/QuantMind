# stock_context 异常来源叶级缺口候选 ready

- 节点 Mac 独立 worktree `/Users/lizeyu/.codex/worktrees/quantmind-tushare-stock-context-invalid-gap`；基线 `0c18fb294a6c2524d8159225bb5f15aa2d38f91f`，分支 `codex/tushare-stock-context-invalid-gap`。仅需 pick `47f239f6f86a36bae5f19571a4da7d66766efab3`，已 push，工作树干净，未部署。
- 5 文件：`backend/shared/tushare_stock_context_contracts.py`；新 `scripts/test_tushare_stock_context_invalid_identifiers.py`；既有 `scripts/test_tushare_stock_context_contracts.py`、`scripts/test_tushare_stock_context_pipeline.py` 两处旧坏叶阻断断言；`docs/tushare-rewards-observed-periods.md`。没有改 pipeline/registry/store/合同元数据/游标/共享 _stocks/documents。
- 承接 start 记录只读取证：`stk_managers` 原文 `X20720.SZ`，object SHA `729eed0e7a6b5dae2e9a723d23c6a3a9f9ceffd9e3fd4b8050f50d77d67ff378`，observation `6b6ea82158db46638a866fe8614da3b7.json`。通过 cloud-compose quantmind python3 -S、SQLite mode=ro、对象 SHA 核验，839 个不同来源/2.323 秒首个发现即停；不代表全库异常全集。报告 `/tmp/stock-context-source-readonly-result.json`。
- 最小修复仅 stock_context 的薪酬库存按叶调用既有严格 _stocks。有效股票继续 code-only，实际已见合法 code/end_date 配对继续补采，异常不修码、不丢原文或 discovery。能力键 `planning:stock_context:stk_rewards:malformed_stock_supplier_identifiers` 为 coverage_unverified，包含非法数/合法数和最多5个类型、SHA摘要；仅短源代码形状可显示原值，任意文本不回显。父级 validation_passed 表示规划恢复，不表示来源完整。
- 配置／容器错误仍阻断该族；其他家族股票校验不变。现有冻结 identifiers 可继续消费，无政策指纹、schema、旧任务、父状态或 checkpoint 重置。原饱和父仍未完成，观察期间全集仍未知。
- Python3.10 专项25项/0.687秒通过；全 `test_tushare*.py` 840项/46.199秒，OK (skipped=5)。日志 `/tmp/stock-context-invalid-target310.log`、`/tmp/stock-context-invalid-full310.log`；Ruff/diff check通过。解释器 `/tmp/quantmind-calendar-factor-test310/bin/python`。
- 新回归使用54个合成等价来源配对，复现混合X代码库存，实际 identifiers→plan_extended 有界推进54全部历史入队，旧validation_blocked恢复、合法近期发现仍有、原对象SHA与quality父逐行不变、重复规划幂等。不是生产54配对逐项重跑或上游全集证明。
- 候选执行中无生产 Pipeline 初始化/Token读取/上游请求/锁/任务配置修改/重启；唯一生产交互为上述授权只读查询。父后续可串行 review/pick、发布，再精确复核 live planning与54来源对，不需重置未完成cursor。
