# 研究工作台双端真实验收完成
- Mac 协调云端；任务 01a08188-b391-7fd3-aa2a-d7c9eef2689d；完成。
- 接续 20260908T173131Z-mac-real-workbench-runs-fd86786.md。分支 codex/research-workbench，完成提交 61f69a3；已逐步合并共享 master。文件范围沿用此前记录，追加 docs/research-workbench-validation-20260909.md，无相邻任务文件改动。
- 两个产品入口、专用服务内队列、持久化窗口、模型退避、计算租约/恢复/绝对截止、真实新公式计算与策略引用均已实现。真实验收与完整课题 ID 见 ../../docs/research-workbench-validation-20260909.md。
- 云端策略与本地方法各 3 实验/9 组合完成；下载 135 个产物逐一校验哈希，18 组账务独立复算通过。页面关闭后继续、计算中 worker 重启、实际取消、暂停后不启动下一步均验收。新因子转策略课题 5276708e41b24369ab613e59aa4d003d 有意保留已暂停，E00 完成。早期失败记录保留。
- 17 项针对性测试、真实隔离 PostgreSQL/Docker 集成、typecheck 通过；绝对截止实际 KILL 测试在 15 秒内完成。云端前端发布成功，最新 AlphaResearchPage-B84pbUUy.js；未重启 Tushare 等相邻服务。临时 qm-research-db-check 已清理；保留本地沙盒与两端 research-worker 供页面后续使用。
- 最近双端 handoff 核验 ee2c5c7，4311 文件，摘要 fc62dadbcfaa18a3b00f302b89d155df852da31076827d6c187650461a0c78b5。后续仅文档与本记录变化，结束时再次核对 Git/源码并推送。
- 当前边界：冻结模板与公式研究，尚非任意论文实现、滚动独立验证或每日模拟；未做连续 8 小时/整机断电测试，历史开发增量不能称盈利。模型本轮已确认 41,838 Token，2 次用量未知，金额未知。CUA download 事件等待未通过，报告 API 下载/哈希通过。
- 下一步：用户可从研究工作台发起新课题；持续方法迭代可优先补独立区间和低相关因子，保留固定合同与失败证据。无本任务未完成开发项。其他 RRG/监控/Tushare 未提交工作保持原样。
