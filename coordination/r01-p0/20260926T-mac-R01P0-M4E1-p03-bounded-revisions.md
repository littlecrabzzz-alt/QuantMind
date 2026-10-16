# 主题：R01-P0.3 R01SELF HOLD 限界修订（p03_execution M4E1）

- 时间、节点、任务标识：2026-09-26 · mac · R01P0-M4E1（wave M4 attempt 1）
- 状态：**done**（四项限界修订全部落地；分红逻辑未动——对方已自驳）
- **新 HEAD（冻结）**：`892694a420822b13f003fa13b4428ad81d48b5fa`（仅 owns 4 文件；此后零提交）
- 证据：`<run>/artifacts/p03/sublot-fix/m4/`（README 前后对照+代码行+对方报告逐条处置索引）；合同附录 rev3

## 四项

1. 零股判定收窄到已证关系：拒单需 total≈available（|差|<1e-9）+0<可卖<100+0<申报<可卖；total≠available（对方静态反例 105/5/3）放行+审计留痕。
2. manual_sell 统一入口：共享 `_sublot_declaration_check` 在 run_day 与 manual_sell 的量截断/撮合前同一校验（reject 带 manual 标记+审计）。
3. checkpoint 订单/成交全精度（to_dict 恢复层原始浮点，0.12003 不再塌成 0.12；展示仅在 export_view）；L901 sizing 取 nav_exact（语义澄清非默改，附录注明舍入边缘差 1 股可能）。
4. 版本绑定：ledger_contract v3.1（附录 rev3）；checkpoint schema 6（precision_semantics=full_precision）；v5 接受为 legacy_precision 不补造；v4 拒；v5/v6 可区分。

## 验证

新增 test_r01_m4.py 16 用例；全量回归 **353 passed**；v2 十窗口 ALL_PASS 残差 0.0%；对方静态反例逐条复跑（105/5/3 → 现在放行 ✓）。daily_binding 纯 H1 现状已入附录 rev3。回信由主控写（对方 coordination 只读）。
