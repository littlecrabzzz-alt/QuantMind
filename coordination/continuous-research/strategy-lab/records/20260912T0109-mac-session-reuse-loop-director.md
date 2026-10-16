# 研究 session 复用与目标驱动 loop

- 时间：2026-09-12 01:09 +0800
- 决策：`session_decision=reuse`
- 现有 session：Herdr `default`，workspace `w1`
- 复用 pane：`qr-glm-0b55`（w1:p4）、`ds-2`（w1:p7）
- 原因：同一 QuantMind 项目、同一 strategy-lab 连续波次；session 正常，pane 可用，合同和本地 run 边界兼容。没有主题隔离、权限冲突或 session 故障理由，不创建新 session。

## loop 调整

旧任务已清理。新 durable 任务：`56a7987a`，每 10 分钟触发，标签 `strategy-lab-research-director`。

新 loop 的工作目标是每次先推荐一项最高价值的研究工序，再在授权范围内推进：推荐必须写明目标、选择理由、负责人和实际模型、输入、交付物、验收证据、阻塞条件及 session_decision。默认复用已有 session；并发不足时扩展原 session；只在隔离或故障条件满足时新建。每次最多推进一个主要工序，不重复计算、不扩大主题、不启动虚拟盘或实盘。

## 当前派发

1. `qr-glm-0b55` / `zai-coding-cn/glm-5.3`：只读复核 S03 修复后的实现与 wave-002 合同，重点检查固定权重、k=0 清仓、排序、逐日重放、checks/schema 和 Qlib API 风险。
2. `ds-2` / DeepSeek：只读执行 S01 ETF B1/U2 准入核查，重点检查固定 release、五只 ETF 覆盖/唯一性/预热和 vol/amount 单位，不产生收益数字。

两项任务互不依赖，均不得改冻结输入、源码、生产配置、数据库或交易开关。
