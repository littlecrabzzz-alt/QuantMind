# Mac Tushare 附件三路下载灰度开始

- 时间、节点、任务：2026-09-18T03:03:39Z，Mac 全量归档所有者，document-gray3。
- 目的：结构化 API 全量采集继续运行时，扩展现有附件下载器的可配置上限至 3，并仅在生产私有配置中灰度启用 3 路；解析仍为单路且不与下载波次重叠。
- 文件范围：`backend/shared/tushare_documents.py`、`backend/services/engine/tasks/tushare_tasks.py`、`scripts/tushare_archive_worker.py` 及对应专项测试。候选在 `/private/tmp/quantmind-document-gray3`、分支 `codex/tushare-document-gray3` 隔离开发。
- 保护：保留全局 `documents.lock`、持久 claim、20 秒单下载预算、五次退避、来源挑战终态、100 GiB/300 GiB 磁盘保护。先离线测试，合入后只在完整周期边界更新 Mac 安装副本，真实验收下载吞吐、失败增量、API 吞吐与 SQLite 健康；云端仍只读研究缓存且不安装全量 writer。
