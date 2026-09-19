# Mac Tushare 大 PDF CPU 限制生产验收

- 时间、节点：2026-09-19T07:13:38Z，Mac 全量归档所有者。
- 代码：`a6c766ab` 提高有界 PDF CPU 时间并识别 SIGXCPU，`3e3db671` 迁移存量误杀项；均已合入、推送 `master`。接续 `20260919T070426Z-mac-pdf-cpu-limit-start.md`。
- 运行时：仓库与 `~/Library/Application Support/QuantMind/tushare-client/backend/shared/tushare_documents.py` SHA-256 均为 `01d64e66c0c239ac29c8d8e0d730c312b1b08c561f017a03df531318ab7de767`；新 LaunchAgent PID 13040。

生产只读复现证明三份有效 PDF 需要约 19、19、30 秒 CPU，旧固定 15 秒限制均以 SIGXCPU 终止并误记 `parser_process_failed`。新上限为 90 秒，父进程墙钟、1 GiB 常驻内存、5000 页、8 MiB 文本和 32 MiB 输出限制保持；SIGXCPU 现在归类为 `parse_timeout`。951 页、43,950,875 字节真实文件经候选正式入口约 28.8 秒成功解析 1,694,931 字节文本。

claim schema v5 事务只将 `downloaded/parse_failed/parser_process_failed` 重置解析次数和到期时间，保留原 PDF、结果及所有 attempts；其他失败状态不变。迁移前有 416 份，部署后首轮开始时 412 份待处理，首个完整周期后降至 364 份。抽核 5 份旧失败已转为 `parsed`，页数为 55、343、361、468、1390，旧失败 attempts 仍可查。

验证：文档专项 103 项、Ruff、diff check 通过；迁移失败回滚保持 v4 和原次数。两次切换均移走 ENABLED、等待自然周期边界和 `disabled`、确认仅剩资源跟踪器后卸载；未强杀下载或事务。首个 v5 周期 108.315 秒，Tushare 759 次请求，文档 83 次下载/39 次解析，API 主链正常；大 PDF 恢复期间附件阶段数会暂降，恢复排空后回归常态。全量本地历史仍未完成，PID 13040 继续运行，云端全量 writer 保持关闭。
