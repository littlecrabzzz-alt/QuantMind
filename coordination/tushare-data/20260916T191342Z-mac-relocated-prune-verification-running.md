# 已迁移归档清理：代码完成，本地复核运行中
- 分支 codex/mac-data-source 已快进 master 并推送 b16ab3fc。
- 负责 scripts/tushare_archive_migrate.py、对应测试和 docs/tushare-mac-source.md；不改业务库、采集算法或研究结果。
- 新 verify-preserved 对冻结清单中的九类不可变文件重新逐文件哈希验收，产出 PRESERVED.json。prune-relocated 默认只读，显式 --apply 才删云端匹配文件；校验交接身份及清单总量、源 CURRENT、三把写锁和每个源文件哈希。源数据库、检查点、停写标记、研究缓存与快照均保留。
- 测试 6 项通过：含损坏本地副本、篡改验收总量、源文件变化、重新 ENABLED、写锁占用、dry-run、不在清单的新文件及重复执行。旧 SQLite 夹具有 ResourceWarning，不影响结果。
- 真正本地复核运行 PID 5615，exec session 92966；已确认进程持续读取 documents 文件，非凭状态文件猜测。不要因观察超时重启。checkpoint-2026-09-16T16-34-47.667824+00-00。
- 采集 PID 98801 保持运行，最近批次 324 请求/90.024 秒。
- 补查云端 quantbot_tasks=0；之前六张研究表无直接版本引用。文件侧 255 个 JSON/JSONL/MD/YAML 均完成检查、无过大跳过，仅 config/tushare-coverage-ledger.json 引用旧版，完整旧版已在 Mac 保存。应用/QuantBot 共用 deployed_read_root；云端已选择 research-cache。
- 当前未删除任何云端文件。待本地复核成功、双端 Git 对齐后传验收文件，运行云端预检及清理，记录实际磁盘空间。只有一个完整快照 snapshot-20260915T230001500000Z，勿直接篡改其内容；下一次 scheduled snapshot 在北京时间 07:00。
