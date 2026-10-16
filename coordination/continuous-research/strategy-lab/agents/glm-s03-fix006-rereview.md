# GLM-5.3：S03 fix-006 独立复核

- agent：`qr-glm-0b55` / `w1:p4`
- 实际模型：`zai-coding-cn/glm-5.3`
- 本地归档：`/Users/lizeyu/.local/share/quantmind/strategy-lab/wave-001-20260911T160311Z/reviews/qr-glm-0b55-wave002-fix006-rereview.md`
- runner sha256：`75f5df27185a016c1bdf0a06a2a7a4c06f9982a4868d4a629258d9d2ebcd17a6`

## Verdict

fix-006 静态/源级复核通过，无需退回 DeepSeek；允许进入受控容器运行。静态通过不等于回测准入通过。

## 已证

- 合同网格为 `100000/300000/1000000 × 0.5/0.95`，runner 从合同读取并拒绝合同外值。
- 场景配置只覆盖 `initial_capital` 与 `risk_degree`，6 场景×3 control 的 54 条输出路径唯一。
- fix-005 固定权重、周频、排序、same-path replay、报告字段、交易开关和未断言 trade_unit 语义均保留。
- `checks_passed` 依赖真实 checks 和 18 组成功运行，不存在字面量伪造通过路径。
- Qlib 0.9.7 源级证据与 runner 调用一致。

## 待查 / 阻塞边界

- 受控容器后验证 18 组账务、k=0 次日持仓、same-path 实际结果、成交权重和不可交易现金行为。
- 容器应挂载共享合同；独立非同路径 replay 未实现，trade_unit 未证实。
- 本轮未启动容器、回测、训练、虚拟盘或实盘。
