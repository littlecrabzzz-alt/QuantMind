# BTC/ETH 现货基线：设计范围

- 时间/节点：2026-10-10 08:49:11 UTC，Mac；研究方法会话。
- 状态：只读索引已完成，独立计划待交接；本轮不运行策略。
- 接续：S03 行业匹配完成记录；停止 S03 新变体和搜参。
- 分工：仅新增 `.local-dev/project/data/research/diagnostics/btc-eth-spot-baseline-20261010T084911Z/PLAN.md` 与本条记录。数据会话负责版本、日期、费用和执行规则准入；父会话负责执行批次协调。
- 已检查：QuantBC / CryptoAdapter / 公共 Qlib 回测 / CN frozen runner / Strategy Lab broker 及 9 月币安验收、GLM 加密执行复核。共有四个既存 tracked 修改未触碰；不访问秘密、Docker、行情载荷或留出。
- 主要缺口：数据读取验收不等于现货撮合验收；UTC 日线与上海时区保留边界须按时间戳重订合同；父会话提及的“资金费 S02”尚未定位，本仓库 Strategy Lab S02 为八因子股票模型。
- 下一步：提交固定参数、有限批次与开始/停止条件的计划；不生成任务来取运行证据，不恢复暂停 GLM。
