# 薪酬追加首位提交候选 ready

- 基线4e4b58d；仅pick `1b5e931a71f4d00bc70ff6703f9bb1a1249d3b9e`，已push `codex/tushare-rewards-append-first`，独立worktree干净。
- 仅3文件：pipeline规划loop枚举5行diff，把stock_rewards_periods首键提前再展开原PLANNERS/APPEND_PLANNERS（Python字典重复键保留首次位置），其余相对顺序完全不变；原test_tushare_rewards_period_append新增2test；既有rewards文档。未改任何预算、已有快照、任务身份、生产配置/DB/队列或服务。
- 专项55 tests /1.626s；Python3.10完整865 tests /43.108s OK skipped5；Ruff/diff通过。完整命令 `PYTHONPATH=scripts:. /tmp/quantmind-calendar-factor-test310/bin/python -m unittest discover -s scripts -p 'test_tushare*.py'`，日志 `/tmp/rewards-append-first-full310.log`，专项 `/tmp/rewards-append-first-target310.log`。
- 两项测试回退到旧末尾顺序均失败（日志 `/tmp/rewards-append-first-before310.log`）。修复后确认所有其他普通/append家族相对顺序保持；后续普通family模拟单调时钟耗时161秒后抛TimeoutError，rollback未提交工作后，从独立SQLite只读连接仍能读取新期间job和已提交offset；原stock_context recent/history所有字段逐项不变。无真实sleep/HTTP，socket/DNS/secret getter被隔离fixture禁用。
- 限制：初始化、identifiers/前置validation发生在循环前，若在那里超时仍不能保证到达追加；本修复只解决普通family先耗尽预算的问题，不宣称planning全局160秒上界已解决。父负责生产串行审查/发布，子任务无生产操作。
