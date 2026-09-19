# 研究子集来源标识去重检查

独立 worktree /private/tmp/quantmind-export-provenance-20260919；负责 scripts/tushare_research_cache.py 和对应测试。当前云端同步 PID 3584159 与本地 source PID 71847 正在处理新版本，保持运行，完成后才部署。

prepare 当前对每个 Parquet 批次的每行 _observation 重复执行路径/成员检查；同一响应通常有很多重复标识。使用 Arrow unique 后检查每个不同标识，所有文件仍执行原有 SHA256 校验，子集不删数据或来源引用。

针对性测试 3 项通过：重复来源引用全部保留；两份不同来源中的损坏文件仍被 SHA256 检查拒绝；既有缓存预算、原子切换和失败保留旧版本检查通过。真实 daily Parquet 批次 5550 行/1 个来源，100 次校验循环：逐行 0.161150 秒，去重 0.004995 秒，来源集合相同。这里只是该检查环节约 32 倍，不是完整发布/同步的提速倍数。当前运行的同步保持原进程，待结束后部署 source。
