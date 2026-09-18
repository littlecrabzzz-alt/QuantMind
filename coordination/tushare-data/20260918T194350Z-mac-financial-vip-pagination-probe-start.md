# 财务 VIP 整期分页实证开始

- 时间、节点、任务：2026-09-18T19:43:50Z，Mac 全量归档唯一写入者，`financial-vip-period-pagination-20260919`
- 状态：受控实证进行中；生产同步继续，探针窗口只在当前周期自然结束后短暂停稳
- 分支与范围：候选代码将在独立 `codex/tushare-financial-vip-pagination` worktree 开发；主工作树只追加本协调记录和后续完成记录
- 依据：官方利润表、资产负债表、现金流量表和业绩预告文档均明确 VIP 接口可用 `period` 获取某季度全市场数据，但没有公开 `limit/offset`。现有 20260914 规划中，`cashflow_vip` 有 14 个全市场父任务因恰好返回 6400 行而拆为 85115 个逐股子任务；`balancesheet_vip`、`income_vip`、`forecast_vip` 也有同类拆分。
- 实证边界：先对已保存为饱和的 `cashflow_vip period=20260630/report_type=1` 使用小页连续 offset 请求，核对页间精确行重叠、终止尾页和首屏复取稳定性；所有响应通过既有不可变对象/observation 入口保存。证据不完整则保留当前逐股逻辑。
- 安全与回退：不输出 Token，不改 `CURRENT.json`，不删除或宣称完成任何现有任务。探针前原子移走 mode-0600 `ENABLED`，等待 worker 自然提交并报告 `disabled` 后卸载；无论探针结果如何均恢复完全相同的 marker 内容/权限并重新安装 LaunchAgent。

下一步：完成单接口实证；若通过，再为各财务 VIP 接口分别验证并实现 opt-in 分页及覆盖闭合后才能压缩重复逐股任务。
