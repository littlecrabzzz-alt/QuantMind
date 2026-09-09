# Qlib 内存修复：真实验证通过，等待 Tushare 发布窗口
- 接续 20260909T014636Z-mac-qlib-memory-a502e78f.md；实际 worktree 起点 6a42202，codex/qlib-memory 尚未集成。
- 分工明确为 qlib_data_builder.py、data_platform/quantdb_hub.py、backend/scripts/rebuild_noncn_qlib_cache.py、scripts/test_qlib_cache_build.py、docs/development-data-contract.md；不涉及 Tushare 文件。
- 云端隔离验证容器 qm-frozen-qlib-memory-verify-v3 已正常退出：1536MiB 限额，143.7 秒，进程 RSS 峰值 560.9MiB，5562 个特征目录、2596 天截至 2026-09-08；无 OOM。结果在 staging/qlib-memory-20260909/output。
- 当前没有在 quantmind 主容器内运行正式构建/发布；尚未替换正式缓存，也未重启共享服务。让 Tushare 本轮先集成/重启；看到其完成记录后再做 Qlib 集成、正式缓存原子发布及读回验收。独立测试继续。
