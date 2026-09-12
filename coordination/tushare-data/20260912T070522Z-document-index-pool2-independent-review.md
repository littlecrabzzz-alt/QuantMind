# Tushare document-index pool2 独立只读审查

- 审查时间：`2026-09-12T07:05:22Z`
- 候选：`63499b79da07c8f0db28f2021b5ee74bcb6df309`
- 分支/worktree：`codex/tushare-document-index-pool2` / `/private/tmp/quantmind-document-index-pool2`
- 基线：`5a110c714ae569ebfd1152f064ea4066efd4ae20`
- 源码 SHA256：`backend/shared/tushare_documents.py` = `04885b85434a527ef27b8fe1431e3c4dc280108954084723ab9b9ba578cb54eb`
- 测试 SHA256：`scripts/test_tushare_document_buckets.py` = `e7f60aec093b6ec9c527e382aa483ef2c0d73adfdc153e92e1cf828a78bab62c`
- 边界：只读审查候选并在临时测试目录运行离线测试；未修改候选、生产、authority、服务或上游。

## 结论

未发现阻塞级正确性、事务、线程安全或字节一致性问题。候选适合保留到下一轮完整阶段基准，但本轮不应部署：现有约 1.711 倍收益只测得 immutable `_save` 子阶段，不能证明生产 `document_index` 的 121.373 秒会得到稳定、显著改善。

## 代码审查

1. `document_index()` 仍在 `BEGIN IMMEDIATE` 后读取固定 dirty 清单，并保持整个 shard/cache/dirty/index 构造处于同一 SQLite 事务。每个 wave 先在主线程完成 SQL 查询、`result` 解码和 canonical JSON 编码。
2. 线程池只收到不可变的 `(root, kind, bucket, count, payload)`，worker 只调用既有 `_save()`。SQLite connection、cache upsert、dirty delete、descriptor 构造和最终 commit 都留在主线程。
3. `list(pool.map(...))` 保持输入顺序，并强制两个 `_save()` 均完成后才更新本 wave 的 cache/dirty。任一 worker 抛出异常时，本 wave 和此前 wave 的 SQLite 变更都由外层 `rollback()` 撤销；`pool.shutdown()` 在退出前等待 worker 收束。
4. `_save()` 仍逐文件写临时文件、flush、`fsync`、hard-link create-only，并在 `finally` 删除临时文件。失败后可能留下已经完成的 content-addressed immutable object，这是原有保留旧 shard 的恢复合同，不会推动 `CURRENT`。
5. 并发不改变 payload、SHA、路径或 descriptor；cache 的最终遍历仍按原排序产生 top index，因此 manifest 和 release identity 保持确定性。
6. 最大并发固定为 2；每次只准备两个 payload，不形成无界 executor 队列或全量 payload 内存增长。零 dirty 和少于两个非空 save 保持串行且不创建线程池。

## 独立验证

- `test_tushare_document_buckets.py`：10 tests passed。
- `test_tushare_document_index.py`：6 tests passed。
- `test_tushare_publish_equivalence.py`：3 tests passed。
- `test_tushare_publish_timing.py`：6 tests passed。
- documents/publish 相关 11 模块合并执行：104 tests passed in 4.609s。
- `py_compile`、`ruff check`、`ruff format --check`、commit diff whitespace check：全部通过。
- 合并测试在 Python 3.13 输出了既有 fixture 的 SQLite `ResourceWarning`；没有测试失败，警告位置分布于未修改的 registration/parallel 测试路径，不构成本候选回归证据。

另做一次不落盘脚本的四个 dirty state leaf 验证，专门覆盖候选持久测试未覆盖的“第一 wave 已成功、第二 wave 失败”：

- dirty buckets：`43c,617,742,955`
- 第二 wave 注入 `OSError` 后，cache、全部 dirty rows 和 `CURRENT` 与调用前逐项相同。
- 临时 fixture 重试成功，release 为 `data-6c658ce890b8dd3f150ed95242b1caf4a5a58f7ff3904b7bfab298b063d21988`。
- 该值只属于自动清理的临时测试目录，不是生产 release 或发布建议。

## 非阻塞测试缺口与发布门

- 候选持久失败测试只覆盖单个两项 wave 的 worker 位置 0/1；跨 wave 回滚由本次一次性离线探针补证，但尚未固化为回归测试。实现的单事务结构和独立探针均支持正确性结论，下一轮若继续修改事务边界，应先把该场景固化。
- 测试覆盖两个 state leaf 的 byte-identical full publish；没有以生产量级 dirty 分布测量 SQLite select/JSON/cache/original-file scan 的占比。这是性能证据边界，不是当前字节正确性缺陷。
- 下一轮部署前必须在相同输入/磁盘条件下比较完整 `document_index` stage，核对 release/manifest bytes、datasets/files/counts、旧新 reader 页面、失败恢复和 `CURRENT`。若完整阶段没有稳定实质收益，应保留串行实现。

