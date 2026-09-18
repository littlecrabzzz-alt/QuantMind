# Tushare：双 HTTP 撤回后云端交接

- 时间、节点、任务：2026-09-18T10:41:49Z，cloud，acquisition-http2-rollback-handoff
- 已验证代码与生产记录：`master` / `bf014978cffc055a51877c7476e310d78df85825`。该提交包含双 HTTP 候选的两个正式 revert 及完整的未保留证据；云端未部署该灰度运行配置。
- `dual_node_check.py --align-git mac` 已通过 Git bundle 快进云端 HEAD；命令最后只因 Mac 本地沙盒 API `127.0.0.1:8000` 未启动而返回 connection refused，该检查发生在 Git 交接之后。
- 云端 `HEAD` 和 `origin/master` 已原子对齐到同一已验证提交，没有修改并行的 RRG/研究工作文件或数据。
- 云端 `dual_node_check.py --node cloud` 通过：同步为 `idle`，drift 为空，errors 为 0，peer completion 100%，6857 个受管内容文件，内容摘要 `32673c3dd5a34be20761db447319b64740f3cee6986ef4793d041819aba046f1`。
- `tushare-research-cache.timer` 保持 active/enabled，最近一次 cache service 以状态 0 退出；研究缓存约 3.1 GiB。
- `quantmind` 容器明确使用 `QM_TUSHARE_READ_STORE=research-cache`；`ARCHIVE_RELOCATED.json` 仍保持 `source_paused=true`。
- 云端没有 Tushare 全量 archive/pipeline worker unit 或进程。

Mac 继续作为唯一全量归档写入者；云端仅按定时器拉取可供研究的子集/缓存。
