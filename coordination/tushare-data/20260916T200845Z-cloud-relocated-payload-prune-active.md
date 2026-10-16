# 云端已迁移不可变副本开始清理
- 原只读预检 quantmind-tushare-prune-check-20260917.service / PID 632645 已正常终止：Result=success、ExecMainStatus=0、MainPID=0、inactive/dead。
- 完成 1209626 个文件 / 219773995368 逻辑字节；archive-cleanup-status.json=dry_run_verified，与 Mac PRESERVED.json 的清单/总量一致。
- 已将只读结果固定保存到云端冻结检查点 PRUNE_DRY_RUN.json，磁盘空闲基线和缓存指针保存到 PRUNE_BASELINE.json，均 0600。位于 data/tushare/.migration/checkpoint-2026-09-16T16-34-47.667824+00-00/。
- 删除前再核验：云端应用 healthy 且读取 research-cache；cache 指向 Mac 新版 data-63ee57e83ba8e0ea954088bb2b4ad82dcf83831ddde14be2dfd3bf9d00feb974；没有 qm-train/agent/frozen/ide/rdagent 活动子容器。
- 已启动 quantmind-tushare-prune-apply-20260917.service，MainPID=704312；--apply=true，2026-09-16T20:05:55.919582+00:00 开始。只按清单删除九类不可变文件，删除前仍哈希核对每份源文件。数据库、检查点、停写标记、研究缓存、唯一完整快照保留。
- 实际进展已验证：archives 中文件由 431 减至 166，/proc/704312/io 已读取约 35.3GB；不要因进度每10000文件刷新而误判卡死。
- 本地 QuantDB PID 6859 继续自动刷新，已 files_applied，派生处理容器 quantmind-dev-quantmind-run-0863664d108a / docker 客户端 PID 16641 仍运行；已补 PG 2026-09-16 共5565行，正在构建 Qlib。等最终校验/自动恢复，不提前启动本地 API。
- 下一步：等待 apply 同一 systemd 单元正常终止，核对 pruned/文件数/独立 df 空闲增量，并重查云端研究读取与本地完整归档；等待 QuantDB applied 和服务 healthy 后重新 handoff。
