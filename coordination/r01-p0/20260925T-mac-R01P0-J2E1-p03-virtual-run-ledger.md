# 主题：R01-P0.3 H2.1-L1..L5 虚拟运行账本（p03_execution J2E1）

- 时间、节点、任务标识：2026-09-25 · mac · R01P0-J2E1（wave J2 attempt 1）
- 状态：**done**（L1..L5 全部交付）
- 提交：`herdr/r01-p0` @ `c64d3853beb61211d9de609c6c684cde0a254f73`（仅 owns 6 文件）
- 证据：`<run>/artifacts/p03/h2/`（README 交付明细+验收映射、account-relationship-audit.md L2 审计）

## 要点

1. **L1**：run_kind="virtual" → `r01vr-<group>-<strategy>-v<version>`（无 attempt 单轨迹，版本变更新轨迹）；同一 R01Ledger 引擎与已验收规则，未另写撮合。
2. **L2**：账户关系审计成文——活盘 simulation_accounts/Redis 键空间完全隔离（无假用户/无共享余额），引擎与 replay 域/checkpoint 复用（r01vr-/r01- 前缀共存），查询走 H1 公共导出只读入口，租户/用户权限沿用；无绕过约束。
3. **L3**：`r01_virtual_run_config`（默认 3 万、2 万粒度检查字段、未配置=待启用）+ `r01_virtual_run_state`（恢复点幂等键 run+date+stage）；DDL/升级 SQL 沙盒两轮幂等；runner 消费接口 `virtual_ledger_config_from_row` / `load_or_create` 已定义（实现归 runner owner）。
4. **L4**：状态随 checkpoint 跨日跨月延续；跨分红 record/ex/pay 窗口崩溃恢复==连续执行逐日全等。
5. **L5**：`r01vr-…:rev<date>` 修订轨迹独立落 run/检查点/证据，原始决策不回填。
6. 测试 14 用例（验收句全覆盖）；全量回归 **316 passed**；v2 十窗口 ALL_PASS 不回归；ruff 全过。
