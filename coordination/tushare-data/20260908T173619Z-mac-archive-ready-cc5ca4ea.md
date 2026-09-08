# 独立归档恢复组件就绪

- Mac / structured_contracts；分支 codex/tushare-structured，独立 worktree；提交 40392d636d98e7fbf3fdb89d7fd5ca8810f4779f。
- 只新增 backend/shared/tushare_archive.py、scripts/test_tushare_archive.py；接续全目录目标及对早期probe遗漏的只读审查。

组件 recover_archive(root,max_items=200,max_seconds=5,rescan=False) 使用独立 archive.sqlite v1冻结首次扫描任务、记录游标、恢复已校验旧data/probe引用与孤立不可变文件。旧manifest原字节复制到archives/<sha>.json，保留release_id映射；不替换旧文件、不重新下载、不读取token、不调用Pipeline。archive_inventory返回files/datasets/gaps/recovery；已知旧Parquet保持API身份，未知孤立Parquet仅证据。
验证：6项离线测试/Ruff通过；初始probe20文件+精确manifest原字节、两旧版本、孤立PDF/提取件/原始观测、KeyboardInterrupt后续跑、坏hash/缺失/路径逃逸/symlink、显式rescan及已解决gap持久审计、同文件跨10旧manifest只hash一次、完成后不迭代目录/读旧文件。
状态complete只代表冻结输入恢复结束，不是供应商历史完整；historical_complete永远false。恢复中缺口持续保留。max_seconds为artifact边界软预算，单个大文件hash/JSON解析/首次目录冻结可能超过，以免大文件永远无法完成。
主任务集成：cherry-pick该提交；publisher合并files/datasets及recovery/gaps，mirror允许archives/<sha>.json，archive.sqlite不参与镜像；后续原始观测重标准化由父负责。完成后正常调用仅SQLite查询；显式rescan用于进程故障或新增未登记文件，重新校验一次，不每120秒重扫。
