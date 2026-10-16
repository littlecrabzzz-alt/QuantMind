# 主题：R01-P0.3 审查修复与记录更正（p03_execution attempt 3）

- 时间、节点、任务标识：2026-09-25 · mac · R01P0-W2E3（wave 2e-fix attempt 3）
- 状态：**done**（p0r1 审查 P0.3 相关发现 1-7 全部修复+补测；发现 8 记录更正见本文件）
- 提交：`herdr/r01-p0` @ `569073ee2672b59e0a828909cedee664f14751be`（仅 owns 文件 11 个）
- 证据：`<run>/artifacts/p03/fixes-w2e3/`（修复清单→测试输出→真实包对账复跑→PG checkpoint 验收）

## 记录更正（审查发现 8）

早前两条 p03 完成记录（20260925T-mac-R01P0-W2E-p03-done.md、…W2E2-p03-integration-done.md）中"真实包/PG 待验证"表述以 attempt 2/3 证据为准更正：

1. 真实包集成验证**已完成**（W2E2，`artifacts/p03/integration-real-package/`：10 窗口三层对账残差 0.0%）；
2. PG 落库路径**已验证**（W2E2 表结构+ORM 往返；W2E3 补齐 client_order_id 唯一约束、TIMESTAMPTZ 口径与**完整账本 checkpoint 持久化验收**：恢复续放与不间断运行 nav 逐日一致、同 run 幂等 upsert、9 项全 True）。旧记录中"完整 checkpoint 延期 P0.5"不再成立。

## W2E3 修复摘要（对应 p0r1 发现编号）

1. **前视（P0）**：调仓目标金额=信号日收盘 NAV、定手数用信号日收盘价（回看≤5 日，不可得 stale_price 拒单）；执行只用开盘价。
2. **顺序/T+1（P0）**：`LedgerOrderingError` 五类显式拒绝（乱序/跳日/非交易日/同日信号/信号错位），signal 缺省自动对齐；T+1 按买入批次逐日解锁（available=qty−pending 恒成立，当日买入当日不可卖）。
3. **量约束（P0）**：成交上限=bar.volume×参与率（默认 1.0 可配），市场量→可卖量→现金级联截断，剩余量全额留痕；allow_partial=False 既有回放行为不变。
4. **涨跌停**：按执行时点价格（R01=开盘价）判封板。
5. **裸卖空**：无持仓/无可卖量卖出拒单 no_position、现金不变；manual_sell 同防护。
6. **PG schema**：client_order_id 唯一约束；confirmed_at/executed_at → TIMESTAMPTZ+aware UTC（UtcDateTime）。
7. **checkpoint**：export/restore + ledger_persistence + replay_ledger_checkpoints 表（升级 SQL upgrade_v1.0.r01replay2.sql 幂等）。

## 验证

- 新增 test_r01_fixes.py 33 用例；全量回归 **242 passed**（含既有 replay/撮合套件）；ruff 全过。
- 真实包对账复跑：10 窗口 ALL_PASS，残差 0.0%（NAV 口径变化使买入目标量移动，对账两侧消费同一 fills 故仍精确对齐；新增 no_lookahead_sizing 断言）；independent-recalc-real.json 重生成，缺行情行日估值回退同口径化。
- 沙盒 quantmind-dev-db：升级 SQL 两轮幂等；pg_w2e3_check.py 9 项全 True。

## 遗留

- 审查 P0.5 必修第 2 项（data-contract.md 目录名 vs 实际 daily/etf_limit 布局的合同冲突）归 p01c 合同变更流程，p03 消费侧已双口径兼容并冻结于 interface-samples.md。
# 主题：R01-P0.3 审查修复与记录更正（p03_execution attempt 3）

- 时间、节点、任务标识：2026-09-25 · mac · R01P0-W2E3（wave 2e-fix attempt 3）
- 状态：**done**（p0r1 审查 P0.3 相关发现 1-7 全部修复+补测；发现 8 记录更正见本文件）
- 提交：`herdr/r01-p0` @ `569073ee2672b59e0a828909cedee664f14751be`（仅 owns 文件 11 个）
- 证据：`<run>/artifacts/p03/fixes-w2e3/`（修复清单→测试输出→真实包对账复跑→PG checkpoint 验收）

## 记录更正（审查发现 8）

早前两条 p03 完成记录（20260925T-mac-R01P0-W2E-p03-done.md、…W2E2-p03-integration-done.md）中"真实包/PG 待验证"表述以 attempt 2/3 证据为准更正：

1. 真实包集成验证**已完成**（W2E2，`artifacts/p03/integration-real-package/`：10 窗口三层对账残差 0.0%）；
2. PG 落库路径**已验证**（W2E2 表结构+ORM 往返；W2E3 补齐 client_order_id 唯一约束、TIMESTAMPTZ 口径与**完整账本 checkpoint 持久化验收**：恢复续放与不间断运行 nav 逐日一致、同 run 幂等 upsert、9 项全 True）。旧记录中"完整 checkpoint 延期 P0.5"不再成立。

## W2E3 修复摘要（对应 p0r1 发现编号）

1. **前视（P0）**：调仓目标金额=信号日收盘 NAV、定手数用信号日收盘价（回看≤5 日，不可得 stale_price 拒单）；执行只用开盘价。
2. **顺序/T+1（P0）**：`LedgerOrderingError` 五类显式拒绝（乱序/跳日/非交易日/同日信号/信号错位），signal 缺省自动对齐；T+1 按买入批次逐日解锁（available=qty−pending 恒成立，当日买入当日不可卖）。
3. **量约束（P0）**：成交上限=bar.volume×参与率（默认 1.0 可配），市场量→可卖量→现金级联截断，剩余量全额留痕；allow_partial=False 既有回放行为不变。
4. **涨跌停**：按执行时点价格（R01=开盘价）判封板。
5. **裸卖空**：无持仓/无可卖量卖出拒单 no_position、现金不变；manual_sell 同防护。
6. **PG schema**：client_order_id 唯一约束；confirmed_at/executed_at → TIMESTAMPTZ+aware UTC（UtcDateTime）。
7. **checkpoint**：export/restore + ledger_persistence + replay_ledger_checkpoints 表（升级 SQL upgrade_v1.0.r01replay2.sql 幂等）。

## 验证

- 新增 test_r01_fixes.py 33 用例；全量回归 **242 passed**（含既有 replay/撮合套件）；ruff 全过。
- 真实包对账复跑：10 窗口 ALL_PASS，残差 0.0%（NAV 口径变化使买入目标量移动，对账两侧消费同一 fills 故仍精确对齐；新增 no_lookahead_sizing 断言）；independent-recalc-real.json 重生成，缺行情行日估值回退同口径化。
- 沙盒 quantmind-dev-db：升级 SQL 两轮幂等；pg_w2e3_check.py 9 项全 True。

## 遗留

- 审查 P0.5 必修第 2 项（data-contract.md 目录名 vs 实际 daily/etf_limit 布局的合同冲突）归 p01c 合同变更流程，p03 消费侧已双口径兼容并冻结于 interface-samples.md。

## 追加（W2E4，复核第 3 项修复）

- checkpoint 跨包校验：restore/load_checkpoint 双层 package_id 绑定（`CheckpointPackageMismatch` 含双方 ID）；测试+沙盒验收 11 项全 True；回归 245 passed、真实包对账不回归。提交 `21cc79d2e37efb223ec97e022b21c2384893e3da`，证据追加于 artifacts/p03/fixes-w2e3/README.md。
