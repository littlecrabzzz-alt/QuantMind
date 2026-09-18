# Tushare：四路文档解析云端交接

- 时间、节点、任务：2026-09-18T09:48:31Z，cloud，document-parse4-handoff
- 生产代码与验收记录：Mac、GitHub 和云端工作树已对齐到 `ee4d2d1c7283f933cfb5ac9e4e25c3b154bafc33`。
- `handoff --align-git mac` 已用验证过的 Git bundle 快进云端工作 HEAD；命令最后只因 Mac 本地沙盒 API `127.0.0.1:8000` 未启动而返回 connection refused，该检查发生在源码和 Git 对齐之后。
- 云端 GitHub fetch 未作为前提；将已验证云端 HEAD 的 `origin/master` 从 `00a486573f6be493899085dfb364de5411aebe4c` 原子对齐到同一 `ee4d2d1c`，没有修改工作文件或数据。
- 云端 `dual_node_check.py --node cloud` 通过：同步 `idle`、drift 空、errors 0、peer completion 100%，6852 个受管文件，内容摘要 `276df2eae2461e5b1c4f22dc7006ef551b4294ea26b64069c7d97b73f080febc`。
- `tushare-research-cache.timer` 保持 active/enabled，`quantmind` 的读取模式仍为 `research-cache`；缓存 service 在定时运行之间 inactive 属于预期状态。
- `data/tushare/ARCHIVE_RELOCATED.json` 仍为 `source_paused=true` 且 owner 为 Mac；云端没有全量 Tushare writer unit 或进程。

Mac 继续作为唯一全量归档写入者并运行四路解析。云端只拉取研究子集，本次没有重启业务容器或恢复云端 Tushare Pro 采集。
