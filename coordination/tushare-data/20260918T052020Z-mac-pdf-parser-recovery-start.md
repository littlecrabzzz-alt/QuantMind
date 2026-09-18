# Mac Tushare PDF 解析恢复开始

- 时间、节点、任务：2026-09-18T05:20:20Z，Mac 全量归档所有者，pdf-parser-recovery。
- 生产证据：文档库有 22580 个 `parse_unavailable`，原因全部为 `resource_limits_unavailable`；其中 20671 个已耗尽 5 次解析重试。原始 PDF 均保留，但本地提取文本不完整。
- 根因：解析子进程同时要求 `RLIMIT_CPU` 与 `RLIMIT_AS`；Darwin 上 CPU 限制可设置，但 AS/DATA/RSS 内存限制均被内核拒绝。现有代码因此在读取任何非可信 PDF 前直接返回 unavailable。
- 方案：隔离 worktree 中保留 Linux 的 `RLIMIT_AS`，Mac 子进程继续使用 CPU 绝对时限，并由父进程通过 `libproc` 监测子进程 resident bytes，超过 1 GiB 即杀死独立进程组；输出写入有界临时文件，保留页数、文本大小和总时限。资源监测不可用时继续保守拒绝。
- 恢复：把 document claim 元数据迁移到 v4，只将 `parse_detail.reason=resource_limits_unavailable` 的已下载 PDF 解析重试归零并立即重新排队；保留原始 PDF、结果、全部历史 attempts 及其他失败/权限状态。
- 验收：覆盖 Darwin resident 监测、内存超限、监测失败、父/子超时、Linux AS 边界和 v3 到 v4 精确迁移；临时复制真实生产 PDF 做只读解析探针，随后在完整周期边界部署并观察 parsed/no_text、unavailable、超时、周期健康和 API 吞吐。
