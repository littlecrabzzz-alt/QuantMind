# 主题：R01-P0.3 M5R 残留补修（p03_execution M5E2）

- 时间、节点、任务标识：2026-09-26 · mac · R01P0-M5E2（wave M5-fix attempt 2）
- 状态：**done**（三残留补修，限界）
- **新 HEAD（冻结）**：`e24ea165cf16468ee1b6485cda8864633d22d232`（仅 owns 5 文件；此后零提交）
- 证据：`artifacts/p03/sublot-fix/m5/`（regression-m5e2.log 377 passed / reconciliation-m5e2.log v2 ALL_PASS，均首行 HEAD；README 追加）

## 三项

1. 精确反例：NAV500/w1/price4 → declared==100（两路断言）；4.008 既有用例保留。
2. 买部分成交不整手化：撮合层买分支去 floor，量约束 fill 精确（200/137→137 余 63）；现金约束可负担仍整手；初始申报 floor 不变。
3. v5 键存在即拒（含 null）；干净 v5 legacy 不变。

回归 377 passed（+5 新用例）；v2 十窗口 ALL_PASS。
