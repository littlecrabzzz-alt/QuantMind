# R01-P0 F 轮独立复验结束：未通过

- 候选 `77b87c2ef2973abb068b2c23bc48ea132eed93bf`，验后 worktree clean；源代码、固定输入和执行组 handover/readiness.json 未改写。
- 原 8 个独立断言 8/8；包 236/236；validator 41；相关单测 105；真实 PostgreSQL 接续 7/7；HTTP 18/21，另真实曲线注册/读回 2/2。
- 原 AC-01～05 定向通过。AC-06 未关闭：实际回报更换 source_revision / manifest_sha256 / input_package_id 仍 applied，3 个真实 HTTP 负例失败。
- 候选 UI 实测：真实文件 API 可读，页面只有文件名不能打开；只绘制 fixture 曲线，缺少真实持仓/现金/订单/净值通路；A/D/N 名称和拒绝事件标签需修正。按既定平台设计 §8 收敛最小适配，优先复用现有模块。
- 本地正常管理员登录与既有网关经过临时接管验证；接管前活动研究任务 0，候选使用独立数据库及工作区。原 sidecar 已恢复并以 capabilities 核对原节点。临时容器、网络、数据库卷、Vite 及凭据已清理。
- 未合并、未部署云端、未启动 A/B agent、持续虚拟盘或实盘；没有更改共享研究数据。独立 verdict=failed；执行组 readiness 仍保持原 pending。
- 报告：`/Users/lizeyu/Documents/ChatGPT/投资/投资学习与研究/课题/R01-P0-F轮独立复验报告-2026-09-25.md`
- 证据：`/Users/lizeyu/Documents/ChatGPT/投资/投资学习与研究/验收/R01-P0-F-20260925T035819Z/`
- 仓库外学习入口、交接入口、验收清单和平台设计状态已同步。本记录不授权研究启动；用户将报告交回同一 P0 组修复后，再带新冻结版本复验。
