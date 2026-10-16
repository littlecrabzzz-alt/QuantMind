# 主题：R01-P0 J2R2 / H2 全链联调完成（p02r 集成收口）

- 时间、节点、任务标识：2026-09-25T09:55Z、mac、R01P0-J2R2（attempt 2）
- 状态：完成（待独立验收）
- 提交：**e3992330**（virtual_run 集成修复）+ **65f634d6**（集成测试更新）；worktree herdr/r01-p0；仅 p02r owns 文件
- 证据：`<run>/artifacts/p06/h2/integration/`（README + 真实链路 12/12 + 故障注入 7/7 + 平台读写回读 JSON/日志 + 复现命令）

## 消除的 J2R1 待联调项

1. **真实日增量链路**：DailyIncrementProvider 现优先消费已发布日包（身份五元组绑定
   d20260918/d20260924 真实 manifest sha/obtained_at）；v2 基线+全部日增量合并为账本
   输入（events 用 event_date 合并修复）；日包 calendar.parquet 分类基线后休市/开市
   （周末=not_trade_day、开市无包=data_blocked）。真实窗口 09-16..09-24 全阶段跑通：
   建仓（真实开盘价）、**511010 份额折算（multiplier 1.00443373）作用于持仓**、
   每日审查无订单、前沿日显式收口、对账、平台回报。
2. **容器链路**：research-agent sidecar 以当前 HEAD 起临时实例（r01 镜像+worktree 挂载；
   原容器主工作树代码滞后无该路由）→ POST/GET roundtrip 真实走通（runner 直写通道补
   x-user-id 身份头——网关应用层依赖）；GET 读回即 R01 页面数据源（含 platform_derived
   派生：stale_heartbeat/paused_risk 判定实测正确）。
3. **故障注入复验**（真实 Redis/PG/数据）：崩溃恢复（含"账本已执行、检查点未落"关键点，
   PG 检查点权威续跑）与重复调度终态指纹==连续运行；风险暂停（真实 09-24 数据触发损失线）
   → 平台 paused_risk+pending_confirmations → 确认恢复。
4. **沙盒恢复**：全部 r01vr-A-fixture-j2r2-* Redis 键/PG 行清理（证据含 DELETE 计数，
   复查 0 行 0 键）；临时 sidecar 删除、原 quantmind-dev-research-agent 恢复运行。

## 流水线语义修正（集成发现，随本次提交）

- 决策窗口开放至次一交易日执行窗口开端（DG-006 真实时间线：D 日分区 D+1 ~00:18 取得）；
- 日历前沿日不视为月末信号（等日历扩展，避免伪调仓）；
- resolve 优先日包；基线内无包日才回退基线（回放/历史场景）。

## 跨模块缺陷（待办，未擅改）

- **p03**：R01Ledger 份额折算后持仓 qty 4dp 舍入 vs independent_recompute 全精度 →
  nav 恒差 ~0.0038 CNY（严格对账 1e-6 失败；两侧均在 r01_ledger.py，归 p03 裁决）。
- **主控**：主工作树 research_agent 滞后 herdr/r01-p0 HEAD，正式页面走通 run_status
  需主分支合入后随 local-dev.sh 重建 sidecar（本次用临时实例完成验证）。
- 备注：调度器决策相位按"当日"派发，与真实节奏（D 日数据 D+1 晨到、决策 D 日）尚差
  一个日包节奏的错位，H3 试运行前需把派发日改为"最新已发布日包日"（已记录，小改）。

测试：virtual_run 33/33（含更新后的集成用例）、ruff 干净。
