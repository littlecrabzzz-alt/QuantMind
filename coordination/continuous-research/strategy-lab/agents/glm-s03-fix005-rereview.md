# GLM-5.3：S03 fix-005 独立复核

- agent：`qr-glm-0b55` / `w1:p4`
- 实际模型：`zai-coding-cn/glm-5.3`
- 本地复核归档：`/Users/lizeyu/.local/share/quantmind/strategy-lab/wave-001-20260911T160311Z/reviews/qr-glm-0b55-wave002-fix005-rereview.md`
- runner sha256：`5834b8d0aa8822ace9b4212bf7db9277cf6d7ee2fe32e99f618e88738fb72b4b`

## Verdict

`fix-005` 静态/源级复核通过，无需退回 DeepSeek；静态通过不等于回测准入通过。

## 已证

- `research_status=needs_independent_validation`。
- `report_metrics` 从实际 equity/positions/fills 派生，覆盖合同所需 turnover、fees/initial capital、actual exposure、cash idle、holdings、rebalance。
- `k_zero_execution_flat` 使用 k=0 周次一交易日的真实 model positions，运行缺证据时为 pending/false，signal-side 仅为补充。
- same-path daily replay 诚实标注为同 reader 路径；固定 `1/20×risk_degree`、周频、排序、None 守卫、`checks_passed` 实算及 paper/auto=false 均保留。
- scan-004 的 Qlib 0.9.7 源级准入证据与 runner 调用一致。

## 待查 / 阻塞

- 受控容器运行后才可验证 k=0 清仓、same-path 结果、成交权重保真和不可交易现金短缺。
- 独立非同路径 replay 未实现；trade_unit 未证实。
- 本次未启动容器、回测、训练、虚拟盘或实盘。
