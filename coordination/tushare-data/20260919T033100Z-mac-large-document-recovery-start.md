# 超过旧大小上限的附件补采

Mac，独立 worktree /private/tmp/quantmind-large-documents-20260919。负责 backend/shared/tushare_documents.py、scripts/tushare_archive_worker.py 及相关终态恢复/worker 测试。两份实际缺失响应长度 286872349 与 297216747 字节，当前 256 MiB 上限拒绝下载。

最小调整：允许最大 320 MiB，生产单文件上限改 320 MiB；仍使用每轮空闲空间减 300 GiB 的文档预算。仅当上限确实增大、声明长度能容纳时允许大小失败立即重试，其他来源失败保留冷却。保留原尝试和错误证据，先自然排空再部署，验证两份真实文件落盘情况。不修改业务后端或云端全量采集角色。
