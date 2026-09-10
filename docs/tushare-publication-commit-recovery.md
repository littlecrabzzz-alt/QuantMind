# CURRENT 已提交、成功时间未提交：按精确身份恢复

基线 `4e4b58d`。父观察到task `4f39c1aa` 超时后CURRENT已指向 `data-e201969a…`，但 `publish_success_at=1789006152` 仍旧；随后正常发布已更新到c59d，因此本候选不对历史e201执行人工补记。无生产操作，无mtime推断，也不提高超时/资源。

原子rename只保证CURRENT内容完整，不能同时保证随后SQLite记账已完成。大清单局部变量释放或signal可发生在两者之间。只记录最终标量会让下次仍due并重发；本修复在现有schema6 `scheduler_state`中保存最小身份凭据，没有新表/新配置/后台任务。

1. 最终manifest已写入、fsync、获得精确SHA后，**在CURRENT swap前**事务记录 `publish_intent:<data-SHA> = int(time.time())`。仅保留一个当前intent。已完成比较的noop也记录该身份，覆盖函数返回释放内存时中断的窗口。
2. 正常返回后，在一个SQLite事务内写旧兼容标量 `publish_success_at`、一个带身份的 `publish_success:<data-SHA>`，再删除intent。方法再核对CURRENT指针未改变。
3. 每次publication_check仍先验证CURRENT指针及 `manifest_at` 的正文SHA。只查询与此CURRENT**完全匹配**的intent；其时间不在未来、且不旧于已有成功时间时，补记同一成功事务。使用intent的原时间，不以恢复时刻重新赠送900秒。若原时间已过期，该轮仍正常发布。

恢复报告带 `checkpoint_recovery=verified_current_intent`、`recovered_release_id`。这是补记已发生的提交，本轮 `performed` 不冒称再次发布。正常cadence之后允许继续既有采集路径。恢复全程位于现有pipeline.lock内；二次指针身份检查和SQLite事务分别防止错误CURRENT关联与半个检查点。

切换前失败：intent ID与旧CURRENT不同，不恢复。缺失/损坏manifest、坏指针或中途身份漂移：报错、不推进。旧checkpoint没有intent：继续旧due规则，即使文件mtime更新也不推断成功。intent比已有成功更旧：不倒退。时钟回拨：强制真实发布检查，不接受未来intent或未来成功时间来无限延期。成功事务失败：标量/身份/intent全部回滚。旧jobs/attempts/规划游标/清单内容均不修改。

旧runtime不理解这些新名称但仍可读schema6；回退会失去这个故障窗口的自动恢复，不应用旧数据库覆盖新增进度。新runtime首次遇到旧版无intent的CURRENT也不能凭空追认；其后一次实际发布或完整noop比较会建立可恢复证据。手动Pipeline.publish仍不直接推进periodic成功标量，只记录intent；下一次periodic检查可识别这次已验证提交。

## 隔离验收

12专项：swap前/后signal、首次无标量、noop后signal、缺失/等长损坏正文、legacy与未来mtime、时钟回拨、过期intent、旧intent、不配套指针、成功事务故障回滚、另一个锁持有者。连同既有发布、序列化、三代字节等价、retain、归档、规划cadence、分区闭包共83项Python3.10通过（1.639秒），Ruff通过。新fixture最初遗漏seed enqueue后的commit导致7项没有触发指针变化；补上真实持久seed后全部通过，没有放宽断言。

```bash
PYTHONPATH=scripts:. python -m unittest \
  scripts.test_tushare_publication_commit_recovery \
  test_tushare_manifest_serialization test_tushare_publish_timing \
  test_tushare_publish_interval test_tushare_publish_equivalence \
  test_tushare_retain_reuse test_tushare_archive \
  test_tushare_planning_interval test_tushare_partition_closure
```

建议父审查合入后，按既有部署流程观察intent→CURRENT→成功时间正常链路；如果真实再次出现swap后超时，下次应出现verified_current_intent并避免重复发布。此修复处理跨存储提交窗口，不宣称序列化或其他单阶段已低于160秒。
