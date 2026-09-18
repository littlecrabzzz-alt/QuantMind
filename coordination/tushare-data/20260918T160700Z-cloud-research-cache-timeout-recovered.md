# 云端 Tushare 研究缓存首次生成超时已恢复

- 事件：2026-09-18 23:47 CST 云端请求新本地发布 `data-96ef14e1…` 时，本地首次准备研究子集约 12 分钟，超过旧客户端 600 秒响应等待；本地继续生成完成，未损坏旧缓存。
- 恢复：23:59 重试在 160 秒内完成，研究子集 `data-afff6006…` 验证通过，下载 14508 个新增文件，缓存 3317837768 bytes，upstream_calls=0。timer enabled/active，service 正常 inactive；云端没有全量 archive writer。
- 修复：候选 `2b0af6da` 合入 master `ecd7b57a`，仅将 loopback `/CURRENT.json` 首次准备等待延长为 1800 秒；单文件超时、50 GiB 缓存预算、100 GiB 保留空间、12 API 白名单和校验逻辑不变。
- 验证：`test_tushare_research_cache.py` 2 项通过，Ruff、py_compile、diff check 通过。云端加载常量 1800；真实无新增拉取 12 秒完成，downloaded_files=0、upstream_calls=0；双端代码/内容哈希一致、Syncthing errors=0。
