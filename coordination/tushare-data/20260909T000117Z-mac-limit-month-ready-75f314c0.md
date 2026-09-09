# limit 历史月窗口纯候选 ready
- 独立 codex/tushare-limit-month-history；基线 fafda74；提交 f2ef0110436bd6f694d73df4768c8c13e8539ec6，worktree clean。
- 仅改 backend/shared/tushare_limit_extra_contracts.py、scripts/test_tushare_limit_extra_contracts.py、docs/tushare-limit-extra-intake.md；未访问生产、修改队列或 runtime；concept e1041f2 保留待接线。
- 历史为同自然月闭区间、首尾裁切，近期 7 日仍 exact trade_date；5 池 / 3 类 / 未知下界 gap 不变。history_partition=calendar_month_v1 进入既有 family 合同指纹，正确使旧 daily offset 失效，无 schema 迁移或无关 family 重置。
- python3 -S -B scripts/test_tushare_limit_extra_contracts.py：11 passed；Ruff、git diff --check 通过。隔离执行既有 assess_response、Pipeline.date_children、_planning_inputs 纯函数；full cap 触发截断、闰月二分 29 日无重叠且保留全部筛选身份。
- 条件：需父真实 exact-day 与 range 样本证明日期过滤、池/类别、隐藏字段及来源行相符后，再首次 enable 前集成。仅未饱和窗减少初始调用；若拆到 D 个日叶子可能 2D-1 日期节点，不能用窗口模拟数宣称实际提速或全历史通过。已有日任务不会清理，本次父确认 limit4 尚未规划，可避免初次生成旧日历史队列。
