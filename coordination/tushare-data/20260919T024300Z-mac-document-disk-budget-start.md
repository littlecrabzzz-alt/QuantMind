# 附件批次磁盘预算

Mac：负责 scripts/tushare_archive_worker.py、scripts/test_tushare_archive_worker.py。隔离 worktree /private/tmp/quantmind-document-disk-budget-20260919。

用户要求本地至少预留 200 GB。现有 300 GiB 仅在轮次入口检查；2500 项 × 256 MiB 的附件批次理论超过 100 GiB 缓冲。拟按每次启动附件阶段时的空闲空间，扣除 300 GiB 后，以单附件上限加解析输出上限计算本轮最大阶段数。磁盘充足时保留当前吞吐。业务后端由其他 agent 负责，本任务不改业务服务。

## 已上线并真实验收

实现提交 104a0410，14 项 worker 测试通过，包含低空间实际调用缩小批次的检查。master 已推送，云端 Git/源码已对齐 fb1581d0；通用 handoff 最后 API 检查仍受本地 8000 未运行影响（另一个 agent 处理）。

原 worker 自然完成当前轮次后替换，新 PID 25110。部署脚本哈希与 master 一致，未修改密钥或采集参数。新版本首轮：

```json
{
  "status": "completed_cycle",
  "updated_at": "2026-09-19T02:46:32.151373+00:00",
  "document_disk_budget": {
    "admitted_stages": 2500,
    "free_bytes": 2073542631424,
    "requested_stages": 2500,
    "reserve_bytes": 322122547200
  },
  "requests": 791,
  "document_stages": 2500,
  "worker_sha256": "e9d2ce1d07663f58b7f6f1599c9499dadba50ea22c204941e469caa3a16cffb8"
}
```

每阶段按附件上限加解析输出上限计费，附件预算不使用 300 GiB 保留区；其中超过用户要求 200 GB 的部分继续为结构化采集及 SQLite 留出缓冲。不删除原始数据，完整历史补采仍在运行。
