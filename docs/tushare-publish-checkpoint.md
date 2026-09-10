# 发布超时：默认关闭的可恢复候选

基线 `0c18fb2`。**本候选未部署，不建议仅凭本地结果启用。它提供恢复边界，不保证任何生产步骤必在160秒内完成。** 不调整Celery160/180限制、资源、队列、上游请求或完整数据范围。

## 证据与根因边界

父任务给出的生产证据：`4b5ef897`、`51d0a598`、`fbd9f87e` 三次 publish_only soft timeout；另 `b07a11b4` 停在 `json_bytes(content)`，下一次143.05秒完成，另有146.3/158.86秒成功发布。没有这些批次的完整分阶段计时，本轮不再访问生产。

源码确认：`0c18fb2` 行2977是 `document_index(self.root)`。停在此处或JSON编码处只能表明累计预算在此耗尽，不能证明该单个函数本身耗时160秒，更不能据此断定CPU、内存或锁竞争。旧 `publish_success_at` 只在完成后提交；失败会重做读取CURRENT、全jobs缺口、所有attempts/stat、archive/document inventory、coverage/closure、前版比较、retain、编码。此前已做覆盖聚合复用及retain_previous共享前任快路径，本次不重复它们。

## 最小协议与调用边界

默认 `publish_staged=False`，原 `Pipeline.publish()` 返回和最终manifest字节保持。显式 `publish_staged=True` 只允许配合正数 `publish_interval_seconds`，到期tick仍只发布，不与采集堆叠。调用者必须持现有 `pipeline.lock`；本工具不新建锁或第二个调度器。

1. **冻结**：原完整扫描/原顺序不变，在coverage/closure后把完整candidate写到私有 `publish-staging/content.json`，再写带SHA/大小/前任ID的version1 `checkpoint.json`。内容文件和journal都采用临时文件、文件fsync、replace、目录fsync。此时CURRENT和成功时间不变。
2. **封存**：下一次读取并核验冻结内容，跳过jobs/attempts/partition扫描；按原比较与retain_previous/archives协议生成最终manifest。先持久化标准 `releases/data-<sha>/manifest.json`，再提交ready journal。此时仍不切CURRENT。noop同样进入ready，但复用原release。
3. **提交**：下一次核验ready最终manifest SHA与安全路径，只允许CURRENT仍为指定前任或已经是本次release。原子切换CURRENT并同步目录，然后清除本候选自己两个暂存文件，才返回release。tick此时才更新publish_success_at。

阶段1/2返回None，tick记录 `publication.status=staged, performed=False, pending=True` 和内容SHA/phase/合作预算；不是已发布。pending journal强制优先于正常cadence；配置关闭staged却有pending会明确拒绝，不能把它当一次普通发布静默越过。

进程在content写后/journal前失败：没有有效journal则重新冻结，旧CURRENT不变。retain后或最终manifest写后/ready前失败：保留content重新封存，继承原有幂等/自归档投影。CURRENT切换后/清理前失败：ready重验同一release后清理，不产生新版本。旧jobs/state/tries/result、attempts、planning游标、capability均不改。冻结后新增数据仍在权威队列/原文中，下次正常发布再收录，不混进冻结快照冒称同时观察。

CURRENT漂移、内容等长损坏、ready缺失/损坏、symlink、非法journal均拒绝，不覆盖前任、不清除诊断文件。无自动rollback/丢弃命令；修复需核对原前像与journal，不能删journal假装已发布。ready文件本身含完整原协议清单；本候选没有把引用预期升级成逐个原文已重新验证。

## 预算与已知上限

`stage_budget_seconds=120` 为合作阈值（方法允许0至130，且不含0）。恢复后完成比较或retain时若已经超预算，不再开始后面的昂贵步骤，保留原content待重试；阶段诊断明确 `budget_exceeded`。它无法打断一个全表SQL、document_index、json.dumps或fsync，也无法保证在阈值前写完checkpoint；这些步骤如果单独过长，仍可能重复超时或没有新进展。**禁止将合作阈值包装成硬上界或生产提速证明。**

每次成功默认需要三个120秒beat机会，发布时延至少增加两个触发间隔，期间仍优先发布。总编码量和暂存I/O增加，最多暂存一个完整candidate及其替换临时文件；最终manifest仍走既有不可变保留机制。没有归档/源文件删除。升级回滚到不识别journal的旧代码前必须先以此版本完成pending，不能用旧DB覆盖新进度，也不能在未完成时禁用配置。

因此下一次是否启用应先获得实际阶段timing/内存/锁证据，确认冻结段加checkpoint编码和封存段均有稳定余量。若冻结段仍接近160秒，下一步需单独对其真实热点做有界扫描或流式编码设计；不能仅继续堆阶段、提高限制或压缩gap/attempt/历史语义。本轮保留默认关闭，其他已通过采集修复无需等它部署。

## 隔离验证

新13项覆盖三代/noop完整字节等价（全部attempt、修订、未知state/API、旧probe archive及嵌套闭包）、重启跳过现场扫描、新进度下版收录、content/journal/retain/编码/ready/CURRENT/清理故障、fsync后中断、等长篡改、丢失/符号链接、配置禁用/延迟、合作预算与成功checkpoint。连同既有发布、归档、retain、规划cadence共66项Python3.10.19通过；Ruff通过。第一轮误传不存在的test_tushare_archive_retention模块导致import error，已用实际test_tushare_retain_reuse重跑通过，不是运行时代码失败。

[机器证据](tushare-publish-checkpoint.evidence.json)：纯临时100000文件引用+100000闭包子节点，最终24304813字节，legacy与staged SHA完全相同。Mac Python3.10单次legacy0.436秒，三阶段0.182/0.437/0.009秒。**总用时更长、最长单阶段没有改善**；该fixture故意只有元数据，不含云端数百万jobs/真实原文/文档写竞争，不能外推生产性能。

```bash
PYTHONPATH=scripts:. python -m unittest \
  test_tushare_publish_checkpoint test_tushare_publish_timing \
  test_tushare_publish_interval test_tushare_publish_equivalence \
  test_tushare_archive test_tushare_retain_reuse test_tushare_planning_interval
python scripts/benchmark_tushare_publish_checkpoint.py \
  --count 100000 --output /tmp/tushare-publish-staged-new-result.json
```

父集成若保留本候选：Git源码需包含新增 `backend/shared/tushare_publish_checkpoint.py`。Mac installer copy名单也需增此一行，才能在安装副本上调用Pipeline.publish；本轮未改mirror归属文件。普通固定版reader和manifest协议不变。没有生产请求/配置/DB/部署变更。
