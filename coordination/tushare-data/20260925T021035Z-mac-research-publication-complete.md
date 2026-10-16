# 重点研究数据独立发布完成
- 状态：完成；节点：mac；代码 3aabc7d7，验收记录 e23b6712 已合入/推送 master。
- 分工结束：native tushare-archive/source 升级窗口释放；ENABLED 恢复，cloud research-cache timer active/waiting、最近 service exit 0。未启停研究计算服务，未修改既有课题固定输入。
- 验证：121 项发布/缓存/归档/调度测试通过。实库独立发布 115 秒、223715 个分区版本，旧缓存分区全部保留、新增 7825；完整 CURRENT 与发布成功检查点未变。
- 源研究版本：data-4bbdff18a0e466a483ae12efb22c15384024ff1b4c06339622f8fcdb304547dc。
- 云端子集：data-076e45d2fad667fdf71e52300260b3dbe557fd3f819147f1e4f8d8daeae34e36；独立来源对应、source_lagged=false，15650 个差异文件已校验。云端实际读取六接口 9/24 行数/日期全部通过，上游请求 0。
- 证据：docs/research-data-independent-publication-20260925-check.json；结果：docs/research-data-priority-20260925-result.md 第二阶段。
- 私有恢复资料：native archive root 下 maintenance/research-publication-20260925，receipt=completed，不含待恢复的 ENABLED。
边界：完整发布仍独占 pipeline.lock；研究发布/云端拉取各 15 分钟加校验时间，非端到端延迟保证；50 GiB 缓存预算仍生效，固定输入不自动清理。R01 六项独立验收必修由原任务修复，没有策略/实盘准入声明。
主工作树原有 research_watch/两份研究文档及本轮并发 AGENTS.md 修改均保留，未纳入本次提交。
