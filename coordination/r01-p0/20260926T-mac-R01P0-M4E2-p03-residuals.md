# 主题：R01-P0.3 M4R 残留补齐（p03_execution M4E2）

- 时间、节点、任务标识：2026-09-26 · mac · R01P0-M4E2（wave M4-fix attempt 2）
- 状态：**done**（三残留补齐，无范围扩展）
- **新 HEAD（冻结）**：`98b876b622add5160a2e9faf12f82ac00db481fb`（仅 owns 2 文件；此后零提交）
- 证据：`artifacts/p03/sublot-fix/m4/`（regression-m4e2.log 360 passed / reconciliation-m4e2.log v2 ALL_PASS，均首行 HEAD；README 追加段）

## 三项

1. 放行审计：total≠available 等放行场景留 sublot_check 痕迹（skipped_unproven_scope/skipped_balance_ge_100/full_declaration/skipped_pre_effective/enforced_reject），run_day 入 DaySummary.sublot_checks、manual 入 sublot_check_log，含 total/available/declared/context/coid。
2. precision_semantics 语义链：schema6 校验标记（缺=拒）；legacy 恢复再导出标记 legacy（不冒充 full）；v5 链路测试固化。
3. 回归 360 passed（+7 新用例）+ v2 十窗口 ALL_PASS，同 HEAD 日志入 m4/。
