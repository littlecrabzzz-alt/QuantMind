# 存量副本复核完成，云端清理预检运行
- 本地 verify-preserved PID 5615 / session 92966 正常退出 0。
- 2026-09-16T19:32:57.582648+00:00 逐文件验证 1,209,626 个不可变文件，共 219,773,995,368 逻辑字节，与冻结迁移清单完全一致。
- 清单 SHA256 ece6a8a2cf1e5f3dc34a2d6dff60e1471a694a85fee7c31f59241a21d25b412e；验收文件保存在两端同名 .migration/checkpoint-2026-09-16T16-34-47.667824+00-00/PRESERVED.json。
- 云端源码 b16ab3fc，双端 handoff 成功。云端单元测试 6 项通过。
- 再次核实云端 ENABLED 不存在、ARCHIVE_RELOCATED 存在、三把采集写锁可取得、quantmind healthy 且 QM_TUSHARE_READ_STORE=research-cache。
- 已启动 systemd 单元 quantmind-tushare-prune-check-20260917.service（只读，没有 --apply）；后续检查其 MainPID、Result、ExecMainStatus 与 archive-cleanup-status.json，勿仅因观察超时重启。
- 此时云端尚未删除数据。只读预检成功后才能执行 apply 并记录实际磁盘回收；数据库、检查点、唯一完整快照暂留。
- 本地唯一采集 PID 98801 保持运行，最新 pipeline-status 为 19:32:53 UTC，仍有 7,729,353 pending，不能宣称历史补采完成。
