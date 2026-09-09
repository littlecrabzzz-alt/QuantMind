# 到期发布优先候选开始
- remaining_markets，Mac独立codex/tushare-publish-first，基线b849e87；父授权紧急修复超soft160的采集90+发布60叠加。
- 仅tushare_pipeline.py tick及内部发布调用次序，相关publish_interval/tick timing tests与短专属doc。保持__init__/next_job/registry/schema/publish方法/beat/worker不变。
- interval>0到期时先验证当前指针/manifest/成功checkpoint，发布已有持久化数据后返回requests0 publish_only，次tick恢复采集；interval0仍末尾发布。失败不前移checkpoint，保留缺pointer/回退/文档普通采集分支。
- 只隔离候选测试，不生产；单独publish若持续超过160仍须后续metadata增长修复。
