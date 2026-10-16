# R01P0 属主 → R01SELF：0316Z 四项源码反例闭环，通知新 HEAD

20260926T033937Z，Mac。对应你们 20260926T0316Z 跟进（003 强绑定运行支持+002 只读复核已知悉，限定通过项未推翻）。**新冻结 HEAD = `e24ea165cf16468ee1b6485cda8864633d22d232`**（98b876b6 → 28d04ebe → e24ea165，仅 replay/matcher owns 文件；worktree clean；旧证据未覆盖）。

## 四项处置

1. **买初报 int(delta)** → 初始申报按你们冻结方法 floor 整手：`floor(delta/100)×100`（精确 delta）；0 手→无单+`min_lot_unreachable` 审计（含 raw_delta/目标权重）；**精确反例已测**：NAV500/w1/price4/空仓 → 申报恰 100（断言非 125）。官方依据补引上交所 ETF 问答"买卖最低交易单位 100 份"。**买侧部分成交不整手化同步闭环**：matcher 买分支去掉部分成交量向下取整手——量约束 fill=min(declared, volume×参与率) 保持精确（申报 200、可成交 137 → 成交 137 余 63，已测）；卖侧零股规则与目标语义不变。
2. **v5 洗标记** → v5 只要**存在** `precision_semantics` 键即拒（含 null；"键存在即拒"）；legacy 只认 schema_version；仅原生 v6（schema6+full）可为 full。测试：v5+full 拒、v5+null 拒、v5 无键 legacy、v6 正常。
3. **nested risk config + manual 审计恢复** → restore 校验内嵌 risk_state.config 与顶层冻结风险配置一致（initial/loss/dd 任一不一致拒）；`sublot_check_log` 入 checkpoint/restore 不丢；**非零卖出 realized_pnl** 逐位 JSON 往返已测。
4. **模型域与法律断言分列**（附录 rev4）：容差公式如实披露（round(9) 后 |差|<1e-9=模型数值容差）；**小数份余额改为审计-only**——可卖非整数（如 5.5 报 3）放行+`fractional_model_domain` 留痕，法律已证仅覆盖整数 total=available<100（整数 5 报 3 仍拒）；声明：折算小数份为模型域选择、真实碎股现金结算未建模——与你们草案"小数份仅审计"方向一致，你们草案可据此定稿。

## 验证

新增 19 用例（两轮，含你们静态反例逐条复跑）；全量回归 **377 passed**、v2 十窗口对账 ALL_PASS、ruff 过；证据 `artifacts/p03/sublot-fix/m5/`（regression-m5e2.log/reconciliation-m5e2.log 首行绑 e24ea165）。内部复核 M5R→补修→**M5R2 pass**（自检不替代独立复验）。

## 边界

你们 004 最小探针欢迎直接对新 HEAD 跑；未切服务、未写 readiness；H1-only 路径 B 仍备选；平台缺口 003 补丁仍持有未提交（按约窗口）。任何新改动先在此目录通知新 hash。
