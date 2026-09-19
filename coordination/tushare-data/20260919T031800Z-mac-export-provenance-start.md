# 研究子集来源标识去重检查

独立 worktree /private/tmp/quantmind-export-provenance-20260919；负责 scripts/tushare_research_cache.py 和对应测试。当前云端同步 PID 3584159 与本地 source PID 71847 正在处理新版本，保持运行，完成后才部署。

prepare 当前对每个 Parquet 批次的每行 _observation 重复执行路径/成员检查；同一响应通常有很多重复标识。使用 Arrow unique 后检查每个不同标识，所有文件仍执行原有 SHA256 校验，子集不删数据或来源引用。

针对性测试 3 项通过：重复来源引用全部保留；两份不同来源中的损坏文件仍被 SHA256 检查拒绝；既有缓存预算、原子切换和失败保留旧版本检查通过。真实 daily Parquet 批次 5550 行/1 个来源，100 次校验循环：逐行 0.161150 秒，去重 0.004995 秒，来源集合相同。这里只是该检查环节约 32 倍，不是完整发布/同步的提速倍数。当前运行的同步保持原进程，待结束后部署 source。

## 完整链路验收

本地提前发布 data-9b2aaccd 固定版，耗时 648.658 秒，其中 document_index 428.184 秒；没有重新请求上游。云端服务于 11:24:04 CST 退出 0，新增 12331 文件、402760344 字节，缓存合计 4558229001 字节（50 GiB 上限），新版本 data-31096977 来源匹配本地固定版。

云端 sw_daily 20260918 从旧版 0 行变为新版 439 行，本地固定版同为 439 行；两端 reader 上游调用为 0，rrg_status 仍为 blocked_data，不能据此声明历史/PIT 完整。

同步完成后才部署研究子集去重代码并重启 source（新 PID 68246）；云端经原 SSH 通道 GET CURRENT 返回正确新版本。archive PID 45320 未重启，最新真实采集周期完成 780 请求。完整证据见 docs/tushare-local-cloud-freshness-production-20260919.json。
