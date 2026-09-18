# Tushare 附件三路灰度：云端交接与缓存验收

- 时间、节点、任务：2026-09-18T03:26:00Z，Mac + `lzy-vm`，document-gray3-cloud-handoff。
- 源码交接：正式 `handoff --align-git mac` 已把云端工作 HEAD 快进到 `32268612b7a3c8030f142e1b7dfb196b280b7a81` 并保留同步工作文件；命令最后因本地沙盒 `127.0.0.1:8000` 未运行而报 connection refused。该失败发生在 Git 快进之后，不影响 Mac 原生归档或云端缓存。云端 `origin/master` 已显式对齐同一提交，三个部署相关文件 SHA-256 与 Mac 仓库一致。
- 数据拓扑：云端 `ARCHIVE_RELOCATED.json` 存在，`tushare-research-cache.timer` active/enabled，没有全量 archive/pipeline writer 服务。Mac LaunchAgent 保持唯一全量写入者。
- 缓存验收：手动触发既有只读 cache oneshot 后，云端从 Mac 新固定版 `data-afcd3fbe300c1e2082c1a172c37d6a8f9c9343b14a2b938302a39da7f1e51e23` 增量取得 16111 个文件、316986378 字节并逐 SHA 验证。云端缓存已原子切到 `data-8c7962970ede37c923bbe59b1aa145c86faec4635730316a0b014583269f99d6`，缓存总量 2639025817 字节，预算 53687091200 字节，上游调用 0；仍只含 12 个研究 API 子集。
- 验收干扰：对活跃的 `pipeline.sqlite` 与 `documents.sqlite` 并行执行完整 `PRAGMA quick_check` 时，两个检查均返回 `ok`，但读锁与 03:17:19 周期重叠并触发一次 `OperationalError`。worker 未退出，下一完整周期自动恢复：101.674 秒完成 752 次真实 Tushare 请求、120 下载 + 120 解析，failed stage 为空，pending 2882632。后续禁止在活跃采集周期并行执行全库 quick-check；需要完整检查时应占维护边界。
