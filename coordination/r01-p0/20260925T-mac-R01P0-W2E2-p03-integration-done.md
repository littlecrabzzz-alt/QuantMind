# 主题：R01-P0.3 真实数据包集成回放（p03_execution attempt 2）

- 时间、节点、任务标识：2026-09-25 · mac · R01P0-W2E2（wave 2e attempt 2）
- 状态：**done**（真实包回放+对账+PG 路径全部通过）
- 提交：`herdr/r01-p0` @ `a4dfd904191b75389bb86fcf3897f41ba2ff7543`（仅 owns 文件 etf_input_package.py 的最小集成适配；attempt 1 基线 `7bf2f4f3`）
- 输入包：`node://mac/r01-etf-daily/v1-fcbabbb7`（p02 已交付；只读未改，manifest_sha256 `cd8b807e…` 加载时强制校验通过）

## 完成

1. **集成修复**（唯一代码改动，消费侧列口径适配）：`etf_input_package.py` 兼容真实包 YYYYMMDD 日期串、vol_shares/amount_cny 已换算列、factors/ 独立复权因子按日 join、etf_limit 交易所涨跌停价优先消费（20190626 起）；fixture 口径行为不变（attempt 1 全部测试仍绿，118 passed）。
2. **9 标的 10 窗口真实包回放**：T+1 信号对齐（signal_date=上一交易日、成交价=执行日开盘价对 raw 文件核验）、公司行动账务全部命中——159934 2025-09-22 ×0.9481（3700→3507.97 精确）、510500 2015-04-15 ×0.2803 与 2022-08-29 ×1.145558、511010/511260 2026-09-18 ×1.00443373/×1.009504（与 factors 比值精确相等）、510300/511090 等分红现金逐笔对账（8700×0.069=600.30 等）、订单幂等（同 client_order_id 重试返回原订单不重复成交）。
3. **三层对账**：①harness 独立重建（仅用包原始 parquet 手工重放）vs 引擎 nav 残差 **0.0%**（阈值 ≤0.36%，p02 口径）；②乘数 vs factors f_e/f_{e-1} 精确相等；③引擎复算 301 行逐日对齐 worst |nav_diff|=0.0001 元。边界：DG-003 缺行日（510500 2015-04-13）显式 no_quote 拒单不虚构成交。
4. **PG 落库路径**（沙盒 quantmind-dev-db，本地库非云端）：升级 SQL 两轮幂等；ORM 写入 replay_risk_events/replay_corporate_actions/replay_orders（新列+expired_unfilled 状态）→ 新会话重读（模拟重启后检查点恢复读取）→ risk_event_id 唯一约束拒重 → 清理零残留，6 项检查全过。完整账本状态 PG 检查点持久化属 P0.5/验收环境（引擎当前为证据导出口径，已记录）。

## 证据

`<run>/artifacts/p03/integration-real-package/`：README.md（命令+退出码+对账结果）、replay-evidence.json（10 窗口全量）、independent-recalc-real.json（真实数据逐日复算 301 行）、run_integration.py、pg_check.py。`artifacts/p03/README.md` 与 boundary-tests.md 已勾销"待 P0.2 集成验证"待办。

## 备注

- 本轮进行中 p02（9f310ea7）/p04（9ca47869）已各自提交，worktree 干净后本任务提交；无文件冲突。
- 真实包 etf_limit 仅覆盖 20190626 起，更早日期涨跌停仍为工程假设（已在 boundary-tests 记录）。
