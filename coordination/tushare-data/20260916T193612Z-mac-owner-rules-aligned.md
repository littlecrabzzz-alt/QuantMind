# 双端开发规则更新
- AGENTS.md 中过时的云端 Tushare 采集、Mac 镜像描述已改成当前已验证部署；保留 QuantDB/业务库云端归属与沙盒隔离。明确 Mac 离线时云端缓存不会自动追新、不回退供应商。
- 提交 f5528450 已合入 master 并推送。
- 云端只读清理预检 quantmind-tushare-prune-check-20260917.service / PID 632645 已实际读取约 25.8 GB，当前处理 archives；ActiveState=active/SubState=running。Result=success/ExecMainStatus=0 在进程仍运行时不是完成证据。
- 继续等待该同一进程，成功须 terminal 状态与 archive-cleanup-status.json 的 dry_run_verified 一致，再启动独立 --apply 作业。不要因 files=0 误判卡死：进度每 10000 文件刷新，最先的 431 份历史清单约 53 GiB。
