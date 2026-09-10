# 薪酬追加预算只计新增 ready

- 基线a22f1079；仅pick `8faad2dc8f618a1ef810866a25ac8e2754f4c72f`，已push `codex/tushare-rewards-new-job-budget`。独立worktree干净，未操作生产。
- 3文件：pipeline仅stock_rewards_periods循环预算改用inserted（其他family仍原attempted/count）；原append专项测试新增4项并将既有耐故障测试done断言与新预算语义保持一致；既有rewards说明。没有改scope顺序、权限、快照刷新、任务身份、time/scan边界或配置。
- 专项Python3.10 59 tests/1.732秒；完整881 tests/43.691秒，OK skipped5；Ruff/diff通过。日志 `/tmp/rewards-new-budget-target310.log`、`/tmp/rewards-new-budget-full310.log`。解释器 `/tmp/quantmind-calendar-factor-test310/bin/python`，完整命令 `PYTHONPATH=scripts:. /tmp/quantmind-calendar-factor-test310/bin/python -m unittest discover -s scripts -p 'test_tushare*.py'`。
- 验证624源组合/前524existing，一轮新增100且done，原524任务逐行不变；624全existing直接stream_end且后续不空转；524existing+601new第一轮仅500new/offset1024，重开后101new/done；existing仍计history_plan_scan_limit（200时停）和history_plan_seconds（模拟每次0.6秒/1秒预算，两次后停），恢复从精确断点继续。
- 不保证同步next/enqueue单次操作的绝对墙钟截止，沿用协作式预算；若时间或扫描预算实际不足，仍可分多轮但不再被500个existing消耗新增名额。无新API请求、生产配置/DB/队列写入或服务操作。
