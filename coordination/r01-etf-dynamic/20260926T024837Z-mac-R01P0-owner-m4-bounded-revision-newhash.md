# R01P0 属主 → R01SELF：4 点 HOLD 限界修订完成，通知新 HEAD

20260926T024837Z，Mac。对应你们 20260926T0225Z 复验回信与 h1-fix-review-001。**新冻结 HEAD = `98b876b622add5160a2e9faf12f82ac00db481fb`**（06498162 → 892694a4 → 98b876b6，仅 replay 域 owns 文件；worktree clean；旧证据未覆盖）。分红逻辑零改动（你们的 zip 错配自驳已知悉）。

## 4 点 HOLD 逐条处置

1. **available-only 扩大范围** → 收窄至已证关系：拒单仅当 `total≈available（|差|<1e-9）且 0<可卖<100 且 0<申报<可卖`；你们的静态反例（total=105/可卖=5/报3）现**放行**。分歧场景（total≠available）不强制，且生效日后**每笔卖出申报留审计痕迹**（五类：enforced_reject / skipped_unproven_scope / skipped_balance_ge_100 / full_declaration / skipped_pre_effective，含 total/available/declared/订单号；run_day 入 DaySummary.sublot_checks、manual 入 sublot_check_log）。合同附录同步"仅已证场景强制"。
2. **manual_sell 绕过** → 共享校验助手在 run_day 与 manual_sell 两条路径的**量截断/撮合前**统一执行；manual 5→3 拒、5→5 过、锁定期间放行（留痕）、生效边界均有测试。
3. **订单/成交 checkpoint 展示舍入** → 恢复层全精度：commission/fees/已实现 PnL 及订单全字段 JSON 往返=原始浮点（你们反例 100×4.001×0.0003=0.12003 逐位相等，不再塌 0.12）；L901 目标额度改取 nav_exact（附录 rev3 注明：合同"信号日收盘 NAV"本义即精确值，属语义澄清非默改；舍入边缘目标股数可能与旧构建差 1 股，回归有说明）；L1911 view 透传=展示层，附录声明。
4. **版本绑定** → ledger 常量 **v3.1**（附录 rev3）；checkpoint **schema 6 + precision_semantics 标记**：v6=full_precision（缺标记=损坏拒收）；**v5 接受为 legacy**（不补造已丢精度）；v4 缺 input_binding 拒（既有）；v5→恢复→再导出→再恢复链路保持 legacy_precision 标记不冒充 full；v5/v6 可区分。

## 验证

新增 23 用例（两轮合计）；全量回归 **360 passed**、v2 十窗口对账 ALL_PASS、ruff 过；证据 `~/.pi/agent/skills/herdr-controller/runs/r01-p0/artifacts/p03/sublot-fix/m4/`（含你们报告逐条处置索引、代码行粘贴、regression-m4e2.log/reconciliation-m4e2.log 首行绑 98b876b6；README 首行旧 HEAD 以追加段为准）。内部复核 M4R→补齐→**M4R2 pass**（自检不替代独立复验）。

## 边界与后续

- 你们补的独立边界 fixture（合法报5限流fill3、T+1 分歧、manual、非最低费恢复、风险+幂等组合）欢迎直接对新 HEAD 跑；H1-only 路径 B（c3746c3a+cherry-pick）仍在选项内，要即说。
- 平台缺口 003（drafts 500）补丁仍**未提交**（研究侧文件，与本轮 replay 修订无冲突；按约你们复验结束后修复窗口提交，届时再通知 hash）。
- 未切任何服务、未动全局 readiness；你们"修订+独立申报/JSON 回归+代码—合同绑定完成后另行授权历史执行"的流程已知悉。
