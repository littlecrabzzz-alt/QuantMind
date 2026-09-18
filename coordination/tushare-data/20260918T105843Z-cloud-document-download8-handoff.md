# Tushare：八路文档下载云端交接

- 时间、节点、任务：2026-09-18T10:58:43Z，cloud，document-download8-handoff
- 已验证代码与生产记录：`master` / `a633708bbc96cbe3467b42dd5061acb65383264f`。Mac 私有运行配置不进 Git，云端不会获得或启动全量归档配置。
- `dual_node_check.py --align-git mac` 已用 Git bundle 快进云端 HEAD；命令末尾只因 Mac 本地沙盒 API `127.0.0.1:8000` 未启动而返回 connection refused，Git 交接在此之前已完成。
- 云端 `HEAD` 和 `origin/master` 已原子对齐；`dual_node_check.py --node cloud` 通过：同步 `idle`、drift 为空、errors 0、peer completion 100%，6860 个受管内容文件，摘要 `e5e9f23874e1f582c3c92e084141599e19dd49c0fef99e82a84b91a260299fee`。
- `tushare-research-cache.timer` 保持 active/enabled，`quantmind` 容器仍明确使用 `QM_TUSHARE_READ_STORE=research-cache`。
- 云端没有 Tushare 全量 archive/pipeline worker 进程。

Mac 继续作为唯一全量归档写入者，云端只拉取研究子集/缓存。
