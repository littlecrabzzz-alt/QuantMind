# 到期轮专用于发布已有数据

自动任务 soft limit 为 160 秒。已有采集约90秒，再叠加约60秒发布、初始化与规划，可能在序列化 manifest 时被中断，导致 CURRENT 连续停在旧版本。本改动分开这两项工作，不调整超时、beat 或 worker 数。

`publish_interval_seconds > 0` 时，tick 取得原 writer lock、磁盘检查并打开持久化队列后，先验证 CURRENT 身份、manifest SHA 与 `publish_success_at`。达到间隔、没有指针/成功 checkpoint 或时钟回退时，直接复用 `Pipeline.publish()`，成功后才写 checkpoint，返回 `status=publish_only`、`requests=0`、`publication.mode=publish_only`。这轮不取供应商 token、不建 HTTP client、不初始化历史任务、不规划或采集；发布已经落盘的尝试、分区和文档版本。

未到期时 `publication.mode=acquire_only`、status仍deferred，原初始化、规划、采集、文档登记继续。若采集期间刚好跨过到期点，本轮不追加发布；下一轮按原120秒beat检查。文档 worker 的原任务派发在调用 tick 前，仍照常执行；publish-only 只是跳过本轮新文档登记。失败沿用状态/耗时记录与异常抛出，checkpoint不前移，下轮继续重试。

`publish_interval_seconds=0`（包括未配置）仍每轮末尾发布；手动 `Pipeline.publish()` 不变。CURRENT/manifest 身份和校验、失败重试规则与固定版本格式不变；不迁移SQLite、Parquet或manifest，不重写已有release。

隔离测试包含60秒publish与90秒acquire分轮计时、采集中跨期、发布轮零上游/零token读取、默认0、坏指针、时钟回退、缺pointer、失败checkpoint保留，以及四批未发布原文/Parquet/文档版本经下一自动轮进入同一固定版并可复制到新mirror。真实部署与CURRENT推进仍须父任务验收。

局限：这只解决采集与发布时间预算叠加。如果元数据继续增长导致单独publish也超过160秒，仍会失败；本改动未解决manifest规模、单轮序列化或全历史容量上限，不承诺无限扩展。
