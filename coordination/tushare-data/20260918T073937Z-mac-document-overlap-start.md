# Tushare：文档下载与解析重叠优化开始
- 时间、节点、任务标识：2026-09-18，Mac，document-overlap
- 状态：进行中
- 分支、worktree、提交：计划使用 `codex/tushare-document-overlap` 与 `/private/tmp/quantmind-tushare-document-overlap`；生产 `master` 继续运行
- 分工：仅负责文档阶段有界下载与单路解析重叠、配置透传、相关测试和文档；不修改其他 RRG/研究文件
- 接续：`20260918T070602Z-mac-document-throughput-planning-scope-production.md`、`20260918T072717Z-mac-document-registration-catchup-production.md`

现状：生产每轮真实拉取，最近三轮分别处理 356、313、208 个文档；定时 `planning` 是队列重算，不是 dry-run。100 秒文档阶段中，下载 wave 与 PDF 解析串行，最近一轮分别约 39.5 秒和 57.1 秒，构成主要吞吐瓶颈。

方案：在隔离临时数据上实现可显式开关的有界重叠；SQLite claim/finish 仍仅由主线程执行，下载最多沿用现有 worker 上限，解析始终最多一个，默认关闭。测试通过后才在生产短窗口灰度，并以真实周期吞吐、错误、资源占用决定保留或回退。
