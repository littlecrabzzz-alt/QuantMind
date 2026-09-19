# 本地登录不可用：更新失败后恢复
- 2026-09-19 Mac；接续 20260916T150400Z-mac-sync-recovery.md。
- 原因：本地 API 停止，8000 拒绝连接；QuantDB 为 files_applied。市场快照视图要求不存在的 vol_in_stock，导致自动重试持续失败，保护逻辑保持 API/研究 worker 停止。
- 负责 backend/scripts/market_snapshot/schema_adapter.py 和对应回归测试；隔离 worktree /private/tmp/quantmind-login-sep19，主树 dbaa1af2。移除计算器完全未使用的 vol_in_stock、Category 必填投影，保留实际使用的必需行情列，未伪造数据。
- 无这两个供应商字段的真实 Parquet 回归测试通过；已续跑既有 apply，不清空数据库、不改账号、不切换云端。市场计算已通过，Qlib 重建中。
- 开工 handoff 因本机连接拒绝未通过；不据此宣称两端已对齐。

- 10:47 恢复完成：apply exit 0，receipt=applied，PG/Qlib/市场分析均截至 2026-09-18；原 API 和研究 worker 自动恢复 healthy。
- /health=200；分别经过 8000 API 和 3000 前端代理，用不存在的测试身份调用登录，均正常返回 401，而非连接失败或 500。未使用或更改用户密码，未声称已代用户完成认证。
- Qlib 构建仍报告上游除权事件缺口，未修改其金融语义；登录恢复不代表这些研究数据问题已解决。
