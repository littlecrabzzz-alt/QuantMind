# R01 平台整体接入：用户 goal 开工
- 节点：Mac local-sandbox；handoff passed，主树 de76004a，现有未提交修改保留。
- 工作树/分支：QuantMind.worktrees/r01-platform-integration / codex/r01-platform-integration，基于公共 M6 候选 4b4ac509；将集成本线程 UI 9011e9b3 与当前主树兼容改动。
- 范围：统一策略存储/API 的版本与脚本登记、公共 R01 运行适配、既有回测持久化/比较/复跑、虚拟运行与现有监控/交易页关联、研究工作台工程记录归档。
- 复用：strategy_storage.py（唯一策略入口）、BacktestPersistence（既有回测库）、R01Ledger 与 virtual_run（公共执行/账本/调度）、现有页面与认证。缺口为业务对象关联和运行适配，不新建平行账务引擎或平台。
- 相邻归属：R01P0 原组继续 owns 公共 replay/matcher 修复；本线程在独立候选集成，不修改该组 worktree/冻结证据/现行 H1 readiness，不改其他研究组脚本原件。
- 用户已授权本地完整接入与虚拟盘能力。真实交易保持关闭；不发布云端或回灌业务库。
- 数据约束：开发截止 2026-03-24；最后半年按已确认规则隔离；R01X-A 旧全历史标已见。原件上传保留原 hash，新执行版本单独登记。
- 验收：真实 API → 策略代码版本 → 回测/复跑 → 独立虚拟账本 → 页面状态；缺数据如实等待，不伪造运行成功。候选测试与独立验收状态分别记录。

## 完成交接（2026-09-26）

- 本地集成完成，HEAD `6f4ed9930987c533a29ee85dfaa14d228ee28d5d`，分支 `codex/r01-platform-integration`，worktree clean；未合入主树、未发布云端。
- 原 13001 前端改为本 worktree；正常 Engine 18083 + 专用 Celery worker 并发2 + 专用 beat，主服务/H1/共享 PG/Redis 保留。启动见 `docs/r01-execution-platform.md`。
- 策略61 v4 与策略62 v3 完整开发回测 2828 日已完成；页面复跑全部 NAV/决策相等。B1/B2/B3 公共信号适配和原件登记，但研究仍 HOLD，没有账户或收益通过声明。
- A 独立30000元账户 `r01vr-A-platform-s61-bdf38e77eef5-v4` 已启用；停止/恢复 effective；下次决策 2026-09-28 16:15，当前无前向账本/持仓/收益。日线后记账，不是实时开盘撮合。
- 55 回归 + Engine 权限测试1通过，typecheck/build通过，API九组检查/50原件对值/实际页面验证通过。交付报告 `handover/platform-integration/REPORT.md`；仓库外完整记录 `投资学习与研究/研究/R01-平台接通/20260926/平台整体接入.md`。
- 9研究课题、130工程归档（本节点105，旧mac节点25目录保留）；历史文件/事件不删除。开发保留段API/runner硬门控，A旧全历史不可重新称盲测。
- 后续统一发布版本→公共API回测→冻结→账户监控；不要让研究组另建撮合或账本。持续运行依赖Mac/Docker/来源数据；前端未设macOS自启。
