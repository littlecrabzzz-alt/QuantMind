# 重复观察的原文复用完成：待集成

- Mac / text_contracts 追加子任务；codex/tushare-text @d7bc6beaa687ced30f352050e9fb4510885db151；接续 6fec793 与 20260908T173039Z-mac-document-queue-ready-f65c432e.md。本提交仍只涉及 backend/shared/tushare_documents.py 与原测试文件。
- 根据 api_name+原始_row_identity（旧记录去除_fetched_at/_observation后稳定hash）+field+URL+expected_mime 复用 downloaded/pending/retry 作业，新的观察reference保留完整；status=reused/reused_pending，返回stats增加reused。
- 原始latest_result.fetched_at保持不变，新增validation_observation指向实际下载的原观察；解析失败但文件已下载也复用并仅本地重解析。元数据、URL或MIME要求不同则新建任务。重复登记同观察保持幂等。
- SQLite v1→v2仅新增复用查询索引，原任务/映射不删除；enqueue用BEGIN IMMEDIATE防并发重复创建。回退旧代码时须保留v2兼容或暂停文档队列，不回滚数据。
- 验证：16项离线测试、Ruff、diff --check通过；覆盖跨观察只下载一次、原下载时间、待处理/重试复用、row/URL/MIME变化、新旧记录、v1迁移。无生产访问/部署。
- 明确缺口：同URL原文静默修订但API元数据不变仍无法被复用逻辑发现，后续须独立周期验证策略；不能将新reference时间声称成新下载时间。
