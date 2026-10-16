# 主题：R01-P0.3 追认 nav_exact 审计字段（p03_execution J7E3）

- 时间、节点、任务标识：2026-09-25 · mac · R01P0-J7E3（wave J7 attempt 1）
- 结论：**追认**（p06 提交 bd9fb0a4 在 r01_ledger.py equity 快照新增 `nav_exact`）
- 审查：① 语义正确——纯增量审计字段，值取自 `_eod` 局部全精度 `nav`（=cash+应收+Σqty×mark 全精度累加，**非二次舍入**，已验证 nav_exact==手算全精度且 ≠round(·,4)）；② 展示口径不变（`nav` 4dp 保留，export_view/checkpoint/账务路径不受影响）；③ 严格对账消费方（recovery.reconcile 与 independent_recompute(round_output=False)）全精度直减，符合 J2E2 精度政策（内部全精度、展示层格式化）。
- 回归：329 passed；v2 十窗口 ALL_PASS 残差 0.0%（不回归）。无代码改动、无新提交。
