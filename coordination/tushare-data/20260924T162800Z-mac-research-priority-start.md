研究所需数据优先实施，Mac，2026-09-25。

接续 `20260924T160056Z-mac-research-cache-current-converged.md` 和本任务审计。用户要求接手实施，重点/非重点分级，先 A 股量价闭环，随后 RRG 信号层。供数修复任务已结束。

基线 master 7f30d40b；候选分支 codex/research-data-priority-20260925，worktree 位于 QuantMind-worktrees/research-data-priority-20260925。负责近期核心行情准入、现有采集权重/快车道与文档资源预算、QuantDB 派生失败报告和水位恢复、已有固定输入准备入口及必要测试/文档。复用现有调度与输入合同，不另建采集系统。

共享主树原有研究文档、research_watch.py 和未提交课题保留；本任务修改仅在独立 worktree 验证后明确合入。发布时先关闭新采集准入、自然排空，再升级原生运行副本并恢复；不停止整套业务服务，不回灌 Mac 数据，不启动策略训练或实盘。
