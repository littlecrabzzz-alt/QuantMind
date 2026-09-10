# Tushare 附件下载/解析主耗时评估开始

- Owner `/root/document_throughput_next`；Mac 独立 worktree `quantmind-tushare-document-phase`，分支 `codex/tushare-document-phase-throughput-20260910`，基线 `b3d482b805534f426672c182b563e8cd2bfdc877`。
- 只审计 `backend/shared/tushare_documents.py` 的真实阶段调度与现有脱敏收据，并在临时目录做无网络离线基准/回归；不访问生产、Token、上游，不修改生产配置或共享主工作树。
- 保留全局 `documents.lock`、最多 2 个下载子进程、最多 1 个解析子进程、原始证据、领取/租约/重试语义和 100 GiB 磁盘保护。候选只有在代表性资源基准证明安全后才改运行代码，否则提交证据与下一项可执行灰度实验。
