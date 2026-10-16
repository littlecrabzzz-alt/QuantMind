# GLM-5.3：S03 修复后独立复核

- agent：`qr-glm-0b55` / `w1:p4`
- 实际模型：`zai-coding-cn/glm-5.3`
- 状态：已完成独立复核；不是运行通过
- 本地归档：`/Users/lizeyu/.local/share/quantmind/strategy-lab/wave-001-20260911T160311Z/reviews/qr-glm-0b55-wave002-rereview.md`

## 结论

修复后的 `s03_worker.py` 与冻结合同主体一致，没有发现字面量伪造通过路径。固定 `1/20` 权重由 Qlib 的 `risk_degree * current_value` 路径缩放为 `risk_degree/20`；`None` 信号返回空决策；空目标对当前可交易持仓按目标 0 生成卖单；排序键和 `checks_passed` 逻辑基本符合预注册要求。

## 待验与阻塞

- 必须用运行产物证明 k=0 周次一交易日持仓为 0，不能只验证信号侧空目标。
- 不可交易持仓、现金短缺和实际指标仍待容器运行。
- `read_day` 应降级描述为同路径逐日重放，除非增加独立分区读取。
- `research_status` 应对齐为 `needs_independent_validation`；换手率、费用/初始资金、实际暴露、现金闲置、持仓数和调仓次数需入 summary 或在报告中可复现地派生。

本次未启动 S03 回测、训练、虚拟盘或实盘。
