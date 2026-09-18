# Mac Tushare 文档阶段上限 1000 灰度开始

- 时间、节点、任务：2026-09-18T04:46:15Z，Mac 全量归档所有者，document-stage1000。
- 依据：持续补位部署后两轮均完成 600 个文档阶段，其中一轮文档任务只运行 80.388 秒，另一轮运行 93.508 秒；当前 600 阶段上限先于 100 秒时间预算结束。
- 调整：只在私有 `pipeline-config.json` 把 `document_worker_max_documents` 从 600 改为 1000。代码已严格接受且测试 1..1000；`document_worker_max_seconds=100`、`document_download_workers=4`、单下载 20 秒、来源保护、失败退避和 Tushare API 限速均不变。
- 验收：保留旧配置哈希，原子替换并保持 0600；配置指纹规划周期不计 API 对比，随后至少比较三个真实周期的文档阶段数、下载/解析、API 吞吐、挑战/超时、失败阶段和磁盘余量。
