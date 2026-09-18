# Mac Tushare 文档终态恢复生产验收

- 时间、节点：2026-09-18T06:33:00Z，Mac 完整归档所有者。
- 代码：`eb1e6ad0 fix(tushare): recover transient document gaps` 已在 `master` 和 `origin/master`。运行副本 `scripts/tushare_archive_worker.py` 与仓库文件 SHA-256 均为 `e9588916c9ada1165df0acf2d4ce0b3d0d2d874b1457e4f58a6a2ad788ba20ae`。
- 离线验证：文档发现套件 89 项、归档 worker 9 项、终态恢复相关 62 项通过；Ruff、`py_compile` 和 `git diff --check` 通过。另用声明长度 26,240,005 字节的真实大 PDF 做有界下载，2 秒内保存完整 PDF 并进入 `parse_pending`。
- 生产配置：`pipeline-config.json` 从 `7b86c87f30918d77f3234f1b0b475af74905121821b8d9ecd7814616ca6306bd` 更新为 `8cf37e57f166b999238da72d36c22dbae2d7b0cad6b64bf348358a962bf6d2b9`，权限保持 `0600`；文档上限为 256 MiB，终态重试单文档冷却 24 小时、每轮最多 16 份。调度器不访问上游，仅把证据完整的候选重新入队；不执行来源脚本、Cookie 或浏览器挑战。
- 切换：先在自然周期末移走 `ENABLED`，确认 worker 写出 `disabled` 且无在途文档子进程，再卸载旧 LaunchAgent、原子写配置、原样恢复 marker 并安装运行副本。当前 `com.quantmind.tushare-archive` 正常运行，配置备份 marker 已消失。
- 首轮：配置指纹变化触发一次 `planning_only`，即队列规划，不是 dry-run 或模拟采集；该轮上游请求为 0，但文档链路真实处理 113 份，恢复调度 16 份，blocked 从 7,445 降到 7,429。256 MiB 上限已在报告中生效。
- 次轮：自动恢复正常采集，100.114 秒完成 591 次 Tushare 请求，`failed_stage=null`；结构化状态为 done 320,931、empty 278,210、pending 2,900,976、blocked 871、permission_blocked 4,693。pending 比部署前短时增加，是队列规划发现新任务，不是已完成数据回退。
- 文档验收：次轮真实处理 209 份并再调度 16 份终态恢复，blocked 降到 7,413；这 16 份逐主键复核全部取得 HTTP 200 PDF，其中 10 份已解析、2 份确认无文本、4 份等待解析。它们覆盖尾空格 URL、较大文件、来源临时挑战、内容重检和瞬时失败五类，证明不是只改变状态计数。
- 当前文档存量：1,688,554 pending、86,016 parse_pending、44,694 parsed、7,413 blocked；归档盘可用 2,464,903,712,768 字节，未触发 NAS 迁移告警。完整本地历史仍在持续补采，不能把本次恢复验收表述为全量完成。
- 双端边界：Mac 继续作为完整归档唯一采集写入者；云端只保留研究子集/缓存，不启用 Tushare 全量 writer。代码和协作记录提交后按 Mac 提交对齐云端 Git，并复核云端 `ARCHIVE_RELOCATED.json` 和研究缓存 timer。
