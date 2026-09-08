# SQLite v5 队列索引候选交接
- Mac / codex/tushare-queue-index；直接基于父 b0e1845；提交6ce645cb1acd8c7fc7b5e3b6c732732c0a133a43。信用候选2a4bbb1仍在codex/tushare-structured，未带入。
- 归属释放：pipeline __init__/next_job/expand、新test_tushare_queue_indexes.py；父另授权既有迁移测试3行版本断言改5（extended_pipeline1行/partition_closure2行）。未部署/生产访问/预算或配额改动。

v5事务迁移增加3个partial index：pending(group_name,priority)、pending(priority)、unexpanded(state,group_name,priority,retry_after)。原索引保留；新查询INDEXED BY避免SQLite仍选旧索引并对同priority行临时排序。隐式rowid顺序保留，expand新索引保留旧group索引后缀/返回次序。全family被API gate阻挡时仍扫描family，本候选不改善该情况或全pending earliest计算。

临时50万jobs/40万pending：小独立SQL实验group6.86→0.00425ms、fallback33.95→0.00421ms、expand31.06→0.00910ms；索引创建0.240s，增加10.2MiB。报告 /var/folders/6m/svdmp5hd6lj09292v8mt73fw0000gn/T/quantmind-queue-index-4iq2ur94/report.json。专项实际schema测试含progress计数因此计时更慢，不能与无计数数据混用；其原查询执行指令至少150万～1440万/3次，新查询约100～200/3次。无生产提速承诺。

验证：5专项（真实v4无索引迁移/重开幂等/第二索引失败回滚无v5标记可重试/公平gate顺序与旧SQL一致/expand行为/40万pending EXPLAIN与结果一致）+17pipeline+11partition+8extended=41通过。Ruff/diff、AST确认只三个授权方法改动。可重跑 uv run --no-project --with httpx --with pyarrow --with duckdb python scripts/test_tushare_queue_indexes.py；原输出 /tmp/quantmind-queue-index-candidate-report.txt。

父灰度下一步：观察initialize一次索引构建和两批acquire/total，比较请求数不突破任何门限；额外索引增加pending写入维护/磁盘成本。v5不删除原数据；旧代码只接受到v4，回退执行代码须保留v5兼容判断，不能直接以旧v4代码打开已迁移数据库。本候选未操作正式schema。
