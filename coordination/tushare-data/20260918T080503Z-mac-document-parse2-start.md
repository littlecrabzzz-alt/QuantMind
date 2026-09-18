# Tushare：双路文档解析灰度开始
- 时间、节点、任务标识：2026-09-18，Mac，document-parse2
- 状态：进行中
- 分支、worktree：`codex/tushare-document-parse2`，`/private/tmp/quantmind-tushare-document-parse2`
- 分工：仅负责文档解析并发的有界配置、主线程事务语义、测试、文档和生产灰度；不修改其他研究/RRG 文件
- 接续：`20260918T080050Z-mac-document-overlap-production.md`

现状：重叠档位连续生产成功，最新轮文档阶段 579，解析器 100 秒预算中占用约 94.5 秒；6 个下载槽总容量约 527 秒、作业约 232 秒，解析仍是吞吐门。Mac 128 GiB 内存、18 个逻辑 CPU、Pages throttled=0。

方案：新增默认 1、上限 2 的 `document_parse_workers`。只有显式启用下载/解析重叠且下载 worker 大于 1 时才允许 2；SQLite claim/attempt/finish 继续只在主线程，单解析器既有 1 GiB/15 秒 CPU/5000 页/输出上限不变。先用隔离临时队列证明解析峰值 2、下载峰值保持有界、总阶段与事务一一对应，再在自然周期边界发布并用真实周期决定保留或回退。
