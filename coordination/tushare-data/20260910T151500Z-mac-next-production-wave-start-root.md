# Tushare 下一生产波次开始

- 时间/节点：2026-09-10T15:15Z，Mac 主集成人；基线 `215ffb0a334154b74c3aa5285ab752bbb24c94dc`。
- 上一波已闭合：`eco_cal` 两个100行父任务零上游重试恢复，48后代24 done/24 empty，闭包收据SHA `31499010…`；第六批财务三表和 `data-66f5a3…` 云/Mac固定版已验收。
- 当前正式写入仍只允许云端 `/data/tushare` 单写者。Mac只读固定版；文档worker因容量缓解保持停用，结构化worker与Beat继续。
- 并行只读分工：financial_batch7_audit 固定第七批三表候选；next_family_priority_audit 比较基金净值/指数权重/公告/份额候选；next_release_capacity_watch 观察下一小时发布、Mac镜像与容量。三者不得读取凭据、访问Tushare或写生产/仓库。
- root 负责唯一生产窗口：等待当前任务和到期发布自然完成，基于固定任务/config/helper SHA串行执行不超过360请求的exact batch，保留100GiB停线、分层限速、不可变原文与不发布契约；之后恢复正常调度并记录终态。
- 终态记录：`20260910T153600Z-mac-next-production-wave-root.md`。自动发布成功，随后串行完成财务三表与 `fund_nav` 两个360请求批次；worker/Beat已恢复。
