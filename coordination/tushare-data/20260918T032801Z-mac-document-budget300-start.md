# Mac Tushare 附件 300 阶段预算灰度开始

- 时间、节点、任务：20260918T032801Z，Mac 全量归档所有者，document-budget300。
- 前置证据：三路附件已连续三个真实 acquisition 周期触及每轮 240 阶段上限，附件耗时约 82.403、50.007、43.443 秒；同期真实 Tushare 请求分别为 762、759、761，failed stage 均为空，source_challenge 保持 5275。
- 变更：只把 Mac 私有 pipeline-config.json 的 document_worker_max_documents 从 240 调到 300；document_download_workers=3、document_worker_max_seconds=90、API 单 HTTP worker、500 次/分钟账户/灰度上限、磁盘保护和失败退避不变。原子替换配置，worker 下周期读取，不重启。
- 验收：观察至少三个完整 acquisition 周期的 API 请求数、附件阶段数/耗时、失败类型和 source_challenge。若出现可重复失败、API 吞吐回退或来源挑战异常增长，回退到 240。
