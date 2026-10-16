# 编排修正：主控定位与并行 worker 池
- 状态：已实施。用户指出“怎么只驱动一个agent”“skill究竟是什么”。
- 根因1：worker池仅 3 agent × 1 pane，exec 池无法并行；GLM 两角色又串行，观感等于 1 路。
- 根因2：旧 SKILL.md（43行）以踩坑条目为主，缺少 worker 池、派发协议、波次 owner 与并行策略。
- 修正：SKILL.md 重写为核心定位/worker池/波次流程/派发协议/并发规则/验收；新增 references/orchestration.md（建池、并行派发、收结果、任务包模板、串位纠正表）。
- 扩容：新增 tab w1:t5 + pane w1:p7，启动 ds-2（DeepSeek Flash）。当前并发 3 路。
- 主控职责边界：只做方向/合同/预算/计算提交/裁决/汇总；实现、调查、审查、复核一律派发。
