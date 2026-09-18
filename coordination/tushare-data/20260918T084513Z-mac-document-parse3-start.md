# Tushare：三路文档解析灰度开始
- 时间、节点、任务标识：2026-09-18，Mac，document-parse3
- 状态：进行中
- 分支/worktree：`codex/tushare-document-parse3`、`/private/tmp/quantmind-tushare-document-parse3`
- 分工：仅扩展文档解析并发上限、测试、说明与生产灰度；不修改其他研究/RRG 文件
- 接续：`20260918T083102Z-mac-document-parse2-stage1600-production.md`

证据：最新周期两个解析槽总容量 189.53 秒、作业 188.68 秒，空闲不足 1 秒；系统 `Pages throttled=0`，128 GiB 内存/18 逻辑 CPU 有余量。双路仍是文档阶段主要瓶颈。

方案：`document_parse_workers` 代码上限从 2 扩到 3，默认仍为 1；三路仍要求下载/解析重叠开启且下载 worker >1。每个解析子进程独立的 1 GiB 常驻内存、15 秒 CPU、5000 页与输出限制不变，最坏解析常驻预算约 3 GiB。SQLite claim/attempt/finish 保持主线程串行。隔离测试须证明解析峰值 3、下载峰值有界、完成阶段和事务一一对应，再在生产原子灰度 2→3。
