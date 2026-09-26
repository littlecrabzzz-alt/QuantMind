# 币安数据云端发布与日更接入
- 用户已要求继续推进上一轮本地数据验收，范围是候选集成、固定数据云端发布、现有市场同步调度接入；追加询问后续币种/股票接入方式，不自动扩大研究池。
- 双端预检通过于 `6a1569cc`；QuantDB PG 修复记录已释放共享合并/服务窗口。本任务接管相关 API / market_sync worker 与必要前端发布窗口，不重启研究 worker / research-agent。
- 复用：`global_market_console` 现有 QuantBC 管理 tab、`sync_schedule` Redis 配置与现有 Celery market_sync 队列、CURRENT 不可变发布、QlibDataBuilder、RD 数据准备。
- 发布前补齐：BC admin 读取 CURRENT；08:15（Asia/Shanghai）调度与 with_qlib 保存；采集长停机后按已有末日补齐；数据准备不开放全局 crypto 研究市场。根目录与产品类型继续隔离。
- 分工：root 负责数据发布、源码/Git对齐、服务空闲核验和验收；products 负责 admin console 版本读取与对应测试；execution_audit 负责调度/UI保存与市场门控；data_fetch 负责长停机回补及测试。候选worktree沿用 `/Users/lizeyu/.codex/worktrees/quantmind-binance-data-20260926`。
- 目标：云端新增 `data/quantbc` 与 `data/binance-tokenized-equity`，没有既有目录，不覆盖业务库、A股数据或研究结果。传到 staging 后逐文件校验，成功才发布；日更先启用 BTC/ETH 的 BC 现有任务，AAPLB 保持独立已验证版本。
- ENABLE_REAL_TRADING 保持 false；前后端全局 crypto 研究开关保持关闭，管理员数据页可独立验收。
