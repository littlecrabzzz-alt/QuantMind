# R01P0-W2P p04 开工记录（2026-09-25T03:0xZ, mac）

- 任务：P0.4 平台与外部 agent 接入（wave 2p attempt 1）。
- 范围：按 p01c/scope.json rev2 p04_platform owns 执行；engine/main.py、App.tsx 冻结不改；
  contracts/** 只读消费（vendored 字节副本入 backend/services/research_agent/contracts/，哈希登记）。
- 计划：external 执行模式 + external-reports 路由（幂等/乱序/哈希/失败语义按 report-api v2）+
  长期多运行课题 + readiness 门控 + 前端 R01 聚合视图 + 测试与本地全链验收；证据出 artifacts/p04/。
- 沙盒使用预告：验证期临时停 quantmind-dev-research-agent，以 worktree 代码另起 r01 容器
  （node_id=mac 的 settings 覆盖副本仅挂载于该容器），完成后恢复原容器；不启动内置模型执行。
