# 云端完整快照保留上限

- 时间/节点：2026-09-16 15:33 UTC，Mac 编码、云端执行。
- 状态：代码已在 master；云端清理已完成。
- 分工：本次只改 `dual_node_snapshot.py`、对应安全测试与部署说明；QuantDB 日常同步由并行任务处理。
- 提交：`3ffd00d0`，后续 master 包含该提交。

云端完整恢复快照现在只保留最新一份已完成版本。创建新快照前、验证发布后都清理更早的已完成版本；`.building`、未完成目录、`quantdb-snapshots`、Mac 已验证的固定研究快照不在清理范围。`prune` 默认演练，`prune --apply` 才执行；中断的删除改名为 `.deleting-*`，下次运行继续清理。快照创建仍保留 100 GiB 空间门槛，不因清理停止 QuantDB 或业务容器。

验证：本地 `PYTHONPATH=scripts python3 -m unittest scripts.test_dual_node_safety` 为 28 项通过、1 项跳过；云端 handoff 对齐到包含该提交的 master 后，dry-run 列出 6 份旧完整快照。`quantmind-snapshot-prune-20260916.service` 用 idle I/O 级别删除这 6 份，退出成功。最终 `snapshots` 仅有 `snapshot-20260915T230001500000Z`、`latest` 和锁文件，`latest/COMPLETE` 存在，再次 dry-run 的候选数为 0。磁盘可用从执行前 113,809,174,528 字节升至执行后 192,858,218,496 字节；这约 79.0 GB 净增长，期间正式采集仍在写入。快照定时器保持 active，业务容器未为此停止。

边界：保留一份云端完整快照控制历史版本增长，但当前快照与活跃项目是两个独立时间点，实际占用不保证精确等于两倍。Mac 固定研究输入仍使用本地已验证快照。下次 07:00 自动创建新快照时，观察新版本发布与旧版自动清理；不要用定时器 active 代替产物验收。
