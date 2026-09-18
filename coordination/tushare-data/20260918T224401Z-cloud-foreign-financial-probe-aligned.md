# Tushare 港美股财报权限验证云端对齐

- Mac/GitHub master 与云端项目 HEAD 已对齐到 `d07f1fc20f583adaf6e96d25e69b99b05bb16fd8`；`handoff --align-git mac` 的 Git 快进成功并保留同步工作文件。
- 联合预检最后仅因 Mac 本地沙盒 API `127.0.0.1:8000` 未启动而返回 connection refused，不影响原生 Tushare LaunchAgent。
- 云端 `tushare-research-cache.timer` 为 active/enabled；`ARCHIVE_RELOCATED.json` 仍为 `source_paused=true`；无 `tushare_archive_worker.py` 或 `tushare_pipeline.py run` 全量写入进程。
- Mac 是唯一全量归档写入者，港股/美股财报 8 个已证实无权限接口保持关闭；云端只继续拉取受限研究子集。
