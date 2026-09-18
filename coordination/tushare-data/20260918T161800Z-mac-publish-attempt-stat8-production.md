# Mac Tushare 发布 attempt 文件校验并行化生产部署

- 候选 `34add160` 已合入 master `c4bee08f`。发布仍逐条读取全部 attempt、逐个 `stat` 全部 observation/object/parquet，并保持原顺序、缺文件失败和完整历史语义；仅将文件元数据检查分成最多 8192 项的有界批次，用最多 8 个线程执行。
- 全套验收：`test_tushare*.py` 1356 项通过，99.463 秒；日志 `/tmp/qm-tushare-full-suite-attempt-stat8.log` SHA-256 `f5775db2039cf2e38e80ab035c3f384cc896794c8499918540e0fc4ce6bfbb08`。Ruff、py_compile、diff check 通过。
- 生产只读 A/B：最近 20000 条真实 attempt 对应 50344 个文件、10344 个 dataset，串行和 8 线程输出指纹均为 `c1fd17a2…`；串行 5.170/5.473 秒，8 线程 1.898/1.989 秒。报告 `/tmp/tushare-publish-attempt-stat8-benchmark-20260919T001200CST.json` SHA-256 `69a8ba77fe095b181ec87f6bace06dd8084b64eaf0fe361a78bcb346cace5b2f`。
- 安全部署：旧 worker 自然完成后进入 disabled，再更新运行副本；新 PID 82296，ENABLED SHA `6b45163b…`、配置 SHA `f13a9045…`、archive.env 0600 保持，运行副本/source pipeline SHA 均为 `07f3d461…`。
- 真实采集验收：新进程首轮 103.325 秒完成 769 次请求及 2454 个文档任务；attempt rowid 756105–756873 全部 HTTP 200，包括 438 sample_ok、330 empty_unverified、1 possibly_truncated，无失败阶段。下一次正常六小时发布将记录完整数据集 `attempt_scan` timing，不额外暂停采集做人工发布。
