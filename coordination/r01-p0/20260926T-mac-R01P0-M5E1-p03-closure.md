# 主题：R01-P0.3 R01SELF 静态反例闭环（p03_execution M5E1）

- 时间、节点、任务标识：2026-09-26 · mac · R01P0-M5E1（wave M5 attempt 1）
- 状态：**done**（四项闭环；对方 coordination 只读，回信主控写）
- **新 HEAD（冻结）**：`28d04ebe1baf432222cb0ca4b1dcea23ba296caf`（仅 owns 5 文件；此后零提交）
- 证据：`artifacts/p03/sublot-fix/m5/`（README 前后对照+代码行+回归/对账日志均首行 HEAD）；附录 rev4

## 四项

1. 买初报 floor 整手：floor(delta/100)*100（125→100 复跑）；0 手无单+min_lot_unreachable 审计（raw_delta+目标保留）；部分成交不整手化；卖侧不动。
2. v5 洗标记封堵：schema5 携带 precision_semantics=损坏拒；legacy 只认 schema_version；仅原生 v6 可 full。
3. nested risk_state.config 与冻结配置一致性校验（不一致拒）；manual sublot_check_log 入 checkpoint/restore（审计不丢）；非零卖出 realized_pnl 逐位往返。
4. 小数份审计-only：可卖非整数放行+fractional_model_domain 痕迹（5.5 报 3 复跑）；整数 5 报 3 仍拒；附录 rev4 模型域与法律断言分列（容差披露/模型假设声明）。

回归 372 passed（+12 新用例）；v2 十窗口 ALL_PASS。
