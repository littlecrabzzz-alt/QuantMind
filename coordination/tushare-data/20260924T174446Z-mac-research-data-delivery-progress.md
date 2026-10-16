# 研究数据优先交付进展

负责人仍为本次数据研究审计任务。代码已合入并 push 至 `90ec0e6b`，两端 handoff 已通过；原有研究文档和 research_watch.py 未提交改动保留。

- 原生采集已加载核心近期准入与优先配置；claim schema 7 索引完成。六个核心接口 9/21–9/24 实际分区通过哈希/行数/日期检查。
- 全量发布 data-fcbabbb7f133dddab1109d3c130653b46041e2c9f6c9cd53b685d3d28f8ac0ab 完成，ENABLED 已恢复，原生 worker 已完成恢复后的周期。
- 两端 PG/Qlib/市场分析后端更新到 9/23；Mac 原有 QuantDB 更新自然完成，未中断。新课题默认使用 research-data-priority-20260925 固定输入，47765 个文件逐项哈希一致，两端 Agent 已核验。未执行训练、回测、付费调用或交易。浏览器验收停在登录页，页面未宣告通过。
- 15 接口子集首次准备超 30 分钟；90ec0e6b 增加较窄已验证子集复用。实库 150245 个旧分区与 300491 个文件描述全部一致，源端约 4 分钟生成新子集 data-0ba57ae05a931a192c45b3615dda9f88ee878743f3c9ede66418eff07d3d9c0d，source_lagged=false。
- 云端现正在补传 24756 个差异文件、约 2.34 GB；旧 CURRENT 保持可读。继续由本任务负责供数/缓存验收窗口，待完成六接口实际读取后追加完成记录。

细节和限制见 docs/research-data-priority-20260925-result.md，最终证据仍在独立 worktree 中补记，稍后合入。
