# Tushare 附件失败闭环：开始

- 时间、节点、任务标识：2026-09-10 07:03Z，Mac，document-failure
- 状态：进行中
- 分支、worktree、提交：`codex/tushare-document-failure-20260910`，基线 `bec7e6aa9fcf6c94ba443dc9976478268c3dccee`
- 分工：只读审计当前附件失败与解析器，负责最小解析修复、测试及脱敏证据；不操作生产配置、服务、凭据或上游。
- 接续：附件双 worker、claim 索引、阶段计时已在生产；本任务不提高并发或任务时限。

本次仅用原子 worker 状态和有 3 秒 progress handler 的自动提交只读查询审计；生产保留 PDF 只复制到本机临时目录并复核 SHA-256。任何候选必须保持原文、哈希、重试、幂等、SQLite 单写者及现有 15 秒解析边界。

下一步：对少量 `parse_failed` 样本离线复现；有共同且可验证的恢复路径才修改代码，否则只提交证据与下一实验。
