# 风险、技术接口及队列调度联合集成
- 节点/任务：Mac，01a0817d-7378-7673-9b7f-59c302713981；状态：进行中。
- 父 worktree：/Users/lizeyu/.codex/worktrees/quantmind-tushare-data-intake，codex/tushare-data-intake；起点3b88631，已包含风险5候选与master 9751b64记录。
- 分工：父负责候选审查、合并、真实探测/验收脚本、最终发布与进度记录；remaining_markets负责technical5纯契约及runtime；text_contracts仅负责pipeline构造器迁移/next_job及structured公平调度；structured_contracts负责111个RRG优先任务的只读落盘/固定版验收。
- 接续：20260909T014311Z-mac-technical-extra-ready-69cfd27f.md及20260909T013953Z-mac-structured-fairness-candidate-review-711108bb.md。
- 当前三名agent已确认running；上一回复仅完成状态核对，没有发布或改变采集。本轮首先整合07a7fde纯契约，再验runtime及可能的schema6迁移。现有采集不暂停；全部候选准备完成后才选择同一次发布窗口。
- 下一步：验证342字段、共享限速和历史cursor保持；真实探测后逐接口启用，空/权限/过滤语义/历史完整性缺口分别记录，不把通过样本当作全量完成。RRG仍blocked_data。
