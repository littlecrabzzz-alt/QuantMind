# Publish 聚合与对象生命周期候选

仅修改 `Pipeline.publish`，schema、清单格式、文件清单、历史观察、缺口与归档闭包均不变。

`coverage_by_api` 的完整 `GROUP BY api_name,state` 查询显式按 `api_name,state` 排序，再求和得到 `coverage`，按同一 SQL 排序的 API 去重得到 `scope`。删除原 status 与 scope 两次额外查询。所有未知状态、未来 API、Unicode 和 NULL scope 均保留；不使用允许列表、不改变 gap 扫描。

`previous` 只在比较 NOOP、保留前任 release、合并归档映射期间需要。最后一次映射合并结束后、`json_bytes(content)` 前释放该引用；最终 content 引用的文件与映射项继续存活。清单序列化仍使用原 JSON encoder、选项和 SHA256，输出字节格式不变。释放对象不保证 RSS 立即下降，尚未测量生产 worker 的内存/耗时收益。

依据前一轮只读测量：10 万 rowid 样本中，GROUP 用时约 0.238 秒，重复 scope 扫描另耗 0.211 秒，派生 scope 与原查询 SHA 相同。实际 worker 是 0.75 核/1 GiB，与测量所用 quantmind 的 3 核/12 GiB 不同，不能据此预测生产时长。状态索引改写未显示收益，本候选不增加或强制索引，也不修改 tick 或发布周期。

专项测试从本地 Git 对象 `a68c6d9` 提取**完整旧 publish 方法**，在相同克隆临时数据根运行新旧实现，比较三代 manifest/CURRENT 的逐字节结果、NOOP、序列化失败后重试、未知状态/API、两份真实 Mock capture/Parquet 观察修订、legacy probe 与历史 release 闭包。每个引用文件核对字节数和 SHA；弱引用验证上一版对象在最终编码前释放。Git 对象须已在开发 checkout 中存在；测试不 fetch，也不需要在无 `.git` 的业务容器执行。

```bash
UV_OFFLINE=1 uv run --no-project --with httpx --with pyarrow --with duckdb \
  python -m unittest scripts.test_tushare_publish_equivalence \
  scripts.test_tushare_publish_timing scripts.test_tushare_archive \
  scripts.test_tushare_pipeline scripts.test_tushare_publish_interval
```

全部使用临时目录与禁网络夹具，不请求 Tushare、不读取凭据、不修改生产数据。完整历史回填/PIT 未因此完成，全部原有覆盖缺口保持。
