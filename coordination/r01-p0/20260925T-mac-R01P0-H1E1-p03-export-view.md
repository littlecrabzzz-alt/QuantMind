# 主题：R01-P0.3 公共展示导出 export_view（p03_execution H1E1）

- 时间、节点、任务标识：2026-09-25 · mac · R01P0-H1E1（wave H1 attempt 1）
- 状态：**done**
- 提交：`herdr/r01-p0` @ `35a7ec6e0d1470965b18af5876d149f7bf7fab0e`（仅 owns 2 文件）
- 证据：`<run>/artifacts/p03/h1/`（README 字段表+版本规则+判别规则、sample-511090-5day-view.json 五日窗口样例、gen_sample.py）

## 要点

1. `R01Ledger.export_view()`（view_schema=1）= `build_view_from_evidence(export_evidence())`：Quickstart/回报示例/页面共用同一入口；审计原件 `export_evidence()` 不动（测试断言派生前后原件逐字节不变）。
2. days[]：逐日 cash/dividend_receivable/market_value/nav（恒等式）/valuation_reliable/持仓（qty/avg_cost/available/mark/mark_source/stale_days/last_mark_date）/当日订单（qty 三态 target·filled·remaining+价格/费用/状态/拒单原因/fills）/当日风险触发；顶层 risk_events/三段式分红/公司行动/banner+session+package。
3. 严格性：必需字段缺失 → `ViewBuildError`（报出 day/订单/字段），不静默填零；非原生形状拒绝。
4. `identify_export_format()` 判别规则（view/evidence/legacy_fixture/unknown）供 p04 前端适配；旧 day_summaries 格式由前端兼容，账本侧只判别。
5. 测试 11 用例（v2 包 511090 五日窗口，G 轮同源：无订单日/部分成交三态/拒单/应收→到账 150 精确/持仓字段/严格性/判别/风险）；全量回归 **298 passed**；v2 十窗口对账 ALL_PASS 不回归。
6. AB-QUICKSTART 已更新双出口（evidence 审计原件 + view 展示）与示例调用。
