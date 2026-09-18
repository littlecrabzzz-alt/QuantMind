# Tushare：四路文档解析灰度开始

- 时间、节点、任务：2026-09-18T09:34:45Z，Mac，document-parse4
- 状态：进行中
- 分支/worktree：`codex/tushare-document-parse4`、`/private/tmp/quantmind-tushare-document-parse4`
- 基线：`master` / `00a486573f6be493899085dfb364de5411aebe4c`
- 分工：只扩展文档解析并发上限、对应测试和说明；不修改 RRG/研究文件或上游限频。

证据：发布后最近五轮中，三个解析槽的总空闲时间分别只有 2.179、1.699、2.663、1.354 和 1.976 秒；对应六个下载槽空闲 64.302–222.088 秒。解析持续饱和，下载仍有余量。系统 `Pages throttled=0`，文档阶段 1800 和六小时固定版发布均已真实验收。

方案：将 `document_parse_workers` 可配置上限从 3 扩到 4，默认仍为 1，多路解析仍要求下载/解析重叠开启且下载 worker > 1。每个解析子进程的 1 GiB 常驻内存、15 秒 CPU、5000 页和输出上限不变，最坏解析常驻预算约 4 GiB；SQLite claim/attempt/finish 继续只由主线程写入。隔离测试必须证明四路解析与四路下载同时有界、每个完成阶段只落一次事务，再进入自然周期边界的生产灰度。
