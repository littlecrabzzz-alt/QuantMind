# Qlib 内存修复与云端缓存恢复完成
- 接续本主题 20260909T014636Z、20260909T021000Z 两条记录。代码 061daf3 已以 42d697d 合入 master/push；本地、GitHub、云端 Git 对齐，handoff passed。Tushare 发布窗口结束后接续，只重启 quantmind，其他 worker 及 US 88fe98db 任务保留。
- 复用原构建器：256MB 单线程 DuckDB、磁盘溢出、按标的流式处理，指数只读相关分区；同盘暂存、文件锁、全字段/日期校验后原子交换。异常不先更新正式日历，维护脚本统一复用同一入口；无新依赖/业务服务，容器内存额度未提高。
- 原因：worker 硬上限 1536MiB，而旧查询配置 8GB 且全市场 fetchdf；内核两次 OOM 导致只更新日历。服务器可用内存不能突破容器上限。
- 验证：Mac 4 项测试通过；合并后源码 Git archive 在无凭据/无网络/只读输入的同生产 amd64 镜像中共 35 项通过。实际云端完整构建在 1536MiB 上限下 143.7 秒，进程 RSS 峰值 560.9MiB、exit 0、OOM=false；进程 RSS 不是含文件缓存的整个 cgroup 峰值。一次中途 schema 失败保留旧完整候选，修复兼容分区 schema 后重建；前后 44506 文件 SHA256 完全一致。
- 正式 /app/db/qlib_data 已原子发布：2596 个交易日截至 2026-09-08，5569 条 instruments、5562 个 features 目录。全字段结构/日期与发布哈希通过，Qlib 实际读取 SH600036/SZ000001/SH000300；股票 close/factor 与当日 QuantDB 未复权价对齐。
- 主容器重新加载代码后 healthy，四后端健康检查通过，3080 返回 200；状态入口 ready=true、lag_days=0。一般 worker 未中断，A 股任务沿用原调度及运行时导入构建器；下一次定时运行尚未发生。状态扫描器的细分 coverage 仍是既有占位字段，完整性结论以此次二进制验证为准。
- 云端证据：/root/data/disk/quantmind/staging/qlib-memory-20260909 的 verify-v3.log、verify-v3-state.txt、output/result.json、output/first-pass-hashes.json。验证容器已移除；成功后回收本次暂存的旧派生缓存和重复候选，保留小型审计产物。
- 数据边界不变：云端原始 QuantDB 未改写；Mac 固定 snapshot-20260908T134413970428Z 未替换或回灌。新云端 Qlib 将随后续完整快照进入下载区，沙盒不自动换版。
