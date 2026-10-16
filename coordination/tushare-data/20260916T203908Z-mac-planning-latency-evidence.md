# 本地规划耗时后续定位

master 79a699d3 双端 handoff 已通过（6691 文件，content digest c4009dbcc9c355ec20bed772b1da5d8df120b72b6bb9cf7349210fce888bf3b2）。
本地 PID 15419 存活且 CPU 时间增加，但 archive-worker-status 最后完成时间停在 2026-09-16T20:30:48Z。未重启。
/usr/bin/sample 15419 1 的真实运行栈显示 islice_next / zip_longest_next / date_strftime 和 SQLite Insert/pread/pwrite；因此不是进程退出，提示历史任务规划/游标跳过耗时。尚未取得 Python 函数级栈，不能仅据此断言根因。
私有采样文件 ~/Library/Application Support/QuantMind/tushare-worker-sample-20260917.txt。
下一步结合 backend/shared/tushare_pipeline.py 的 plan_extended/islice 游标逻辑，隔离重放验证长周期来源；不要中断现有写入或用零请求报告直接判定卡死。
