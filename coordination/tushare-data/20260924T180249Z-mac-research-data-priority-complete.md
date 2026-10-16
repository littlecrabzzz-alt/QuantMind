# 研究数据优先交付完成

本任务释放共享供数/采集维护窗口。已核对上一任务“存储空间”的完成结果，在其代码上继续实施，没有覆盖既有研究文件。

代码：fb7f77d6（近期准入、正文索引与优先级）；e528a6df（派生失败状态、固定输入数据根）；881be655（15 接口子集）；90ec0e6b（扩充接口时复用已验证子集）。均已合入并 push。最终报告与证据另以文档提交收尾，详见 docs/research-data-priority-20260925-result.md。

- 两端源码/Git/健康 handoff 在 90ec0e6b 通过；实际进程已按职责加载变更。未重建镜像，未重启无关服务。
- Mac 原生唯一采集者恢复并持续完成周期；ENABLED 存在，临时 ENABLED.publication 已恢复，pipeline/documents 手动发布锁已释放。全量 release 为 data-fcbabbb7f133dddab1109d3c130653b46041e2c9f6c9cd53b685d3d28f8ac0ab。
- 云端 15 API 子集为 data-0ba57ae05a931a192c45b3615dda9f88ee878743f3c9ede66418eff07d3d9c0d，24756 个差异文件校验并原子切换完成；source_lagged=false，缓存约 8.93 GB，预算 50 GiB。一次性拉取服务成功退出，既有 timer active/waiting。
- 云端真实 read_dataset 六接口 9/24 验收：daily 5557、adj_factor 5569、daily_basic 5557、stk_limit 5648、suspend_d 13、moneyflow 5557；日期/行数与 Mac 原始分区一致，查询未调用上游。
- 两端 QuantDB PG/Qlib/市场分析后端本次验收到 9/23；Mac 原有更新自行完成，没有中断。新课题默认固定输入 research-data-priority-20260925 已启用，两端 47765 个文件逐项一致，读取 4560471 行；旧课题/固定输入保留。
- 测试记录：114 项 Tushare 回归、45 项队列/流水线、12 项正文 worker、29 项同步/派生/固定输入、9 项研究缓存测试通过。没有执行训练、策略回测、付费研究调用或交易。

剩余工作：结构化研究发布仍与全量正文索引耦合，本次完整发布约 34 分钟；部分除权事件、历史成员与财务 PIT、执行约束接入仍需按课题验收；浏览器停在登录页，登录后的页面未验收；本地 QuantDB 应用停机窗口仍需后续改善。详细证据、回退位置与节点固定输入版本均已留档，无遗留人工暂停开关或待恢复服务。
