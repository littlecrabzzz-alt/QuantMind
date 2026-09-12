# Tushare 下一接入缺口只读审计：优先离线核验 `cyq_chips` 无数据签名

- 记录时间：2026-09-12T06:30:26Z（Asia/Shanghai 14:30:26）
- 审计边界：只读代码、进度文档、`pipeline-status.json` 和一次短 SQLite 聚合；未读取凭据，未调用 Tushare，未修改服务、生产数据或 authority。
- 部署代码 pin：`69a7c4737760202f4e26c6546378f08e42904225`
- 状态快照时间：`pipeline-status.json.updated_at=2026-09-12T06:19:02.848526+00:00`
- 状态快照 release：`data-85ffcb29...`（状态文件中本轮读到的缩写；本文不把它用作可执行 release pin）

## 结论

下一轮优先做 `cyq_chips` 的**离线错误签名审计**，随后仅在证据唯一、稳定时增加 API 专属的“明确无数据”分类。当前 102 个 `blocked` 任务累计 510 次尝试，符合每项重试到第 5 次才终止的现有行为；若这些任务确实只有一个供应商明确无数据签名，窄分类可以直接消除相同请求未来的 4 次无效重试，同时保留覆盖缺口，不能把它记作已完成历史覆盖。

`research_report.file_name` 是第二优先级的离线字段合同审计。它当前主要造成 `quality` 分类，不阻断已有行进入规范化与发布路径，因此不要占用当前部署窗口，也不要重拉历史。

## 生产只读观察

下列 per-API 统计来自本轮一次短 SQLite `SELECT ... fetchall()`。查询发生在 2026-09-12 14:25:01 CST 报告 `database locked` 之前；查询耗时 7.517 秒，使用 SQLite URI `mode=ro` 和 `PRAGMA query_only=ON`，并在 `finally` 中显式 `close()`。远端 Python 进程已正常退出，没有遗留 cursor、事务或连接，因而不可能在 14:25:01 后持续持有本轮读锁。为避免影响 writer，本轮此后没有再次打开生产 SQLite。

### `cyq_chips`

| state | jobs | tries sum | rows |
|---|---:|---:|---:|
| blocked | 102 | 510 | 0 |
| done | 459 | 459 | 200,021 |
| empty | 34 | - | 0 |
| pending | 93,966 | 11 | 0 |

这同时证明两点：该 API 已取得真实历史数据，且失败重试仍在消耗请求预算。进度记录还把当轮剩余 2 个业务错误归为供应商“标的/日期无数据”；不能仅凭这句摘要直接写宽泛规则，必须从已保留 raw object 中验证精确业务码、规范化消息和请求形状。

### `research_report`

| state | jobs | rows |
|---|---:|---:|
| done | 46 | 6,650 |
| empty | 25 | 0 |
| pending | 501 | 0 |
| quality | 319 | 36,004 |
| split_pending | 197 | 197,000 |
| resolved | 1 | 1,000 |

现有两个留存样本都缺 `file_name`：一个 1,000 行 capped 响应和一个 2026-01-21 的 85 行 exact 响应。官方输出表不列该字段，但示例出现过它。当前合同把常规 10 列作为 required、把 `file_name` 作为 extra field；`schema_gap` 行仍被规范化，因此这里是可观察字段缺口，不是 36,004 行数据丢失。

### 已有覆盖，下一轮不重复接入

- `moneyflow_hsgt`：done 393 / rows 394；empty 212；pending 3,726。
- `ggt_daily`：done 377 / rows 381；empty 229；pending 3,726。
- `ggt_top10`：done 378 / rows 3,920；empty 227；pending 3,726。
- 上述三个 legacy Connect 合同、planner 和 2014-11-17 起始历史范围已经存在，不应重复探测或另造 runner。
- `ggt_monthly` 仍没有任务；公开页面缺失且真实 API 名曾返回 40101，当前没有足够证据做安全的小修复。
- `index_daily`、`index_weight`、`fund_share`、`fund_portfolio` 已有多轮 exact 批次，本建议不重复这些批次。

## 下一轮最小验证方案

1. **只读离线归类 102 个 `cyq_chips blocked` 任务。**
   - 沿 job → result/attempt → observation → raw object 读取已保存响应。
   - 输出每个任务的 API、canonical params、HTTP 状态、供应商 business code、规范化 message、attempt 次数和 raw object SHA。
   - 按 `(business_code, normalized_message, request_shape)` 分组，并证明每个候选组的数量与 102/510 汇总一致。
   - 不请求上游，不改变旧 job/result/attempt/object，也不将 blocked 批量改为 empty。

2. **仅在签名证据稳定时做 API 专属分类。**
   - 在已知 `api_name` 的 `capture_sample` 邻近层复用通用 `assess_response`，只为 `cyq_chips` 的精确业务码和精确无数据消息增加映射。
   - 映射目标为 `empty_unverified`；保留 raw object/observation，明确 `coverage_proven=false`、`history_complete=false`。
   - 禁止把通用中文“无数据”正则加入全局 intake；相邻业务码、近似消息、限速、权限和系统错误仍必须保持原分类。

3. **定向验收。**
   - 直接测试入口：`scripts/test_tushare_intake.py`、`scripts/test_tushare_pipeline.py`、`scripts/test_tushare_technical_extra_pipeline.py`。
   - 必须证明：精确签名首次响应后终止为 empty；近似签名仍为 api_error；rate/permission 分类不变；raw/observation 始终留存；现有有数据响应仍正常入库。
   - 灰度只让普通 technical-extra 队列自然处理；继续保留 `cyq_perf` 每日 200,000 次硬账本与现有保守分钟速率。

4. **条件性检查 `research_report`。**
   - 离线遍历全部 `research_report` observations，验证 319 个 `quality` 是否都只因 `file_name` 缺失。
   - 若完全一致，保持 10 列常规采集，把 `file_name` 留作显式字段缺口和低频 schema audit；不静默删除字段、不回写旧状态、不重拉历史。
   - 若存在其他缺列或质量原因，保持当前合同，按原因另行审计。
   - 直接测试入口：`scripts/test_tushare_text_contracts.py`、`scripts/test_tushare_field_coverage.py`、`scripts/test_tushare_pipeline.py`。

## 未解决边界

- 尚未离线逐对象证明 102 个 blocked 是否都是同一个供应商签名；因此下一步先完成离线审计，再依据签名证据决定分类实现；这里不新增用户审批要求。
- `empty_unverified` 只表示本次标的/日期返回无数据，不能证明该分区、该标的或全历史完整。
- `research_report.file_name` 的官方示例与输出表不一致；在更多留存样本归因完成前，不能将其宣称为稳定缺失或从覆盖要求中移除。
- `ggt_monthly` 的 API 名、权限和历史字段仍不确定；没有上游证据前不接入。
- `etf_basket` 对 RRG 有研究价值，但 PIT 映射、历史有效期和 PCF 语义仍未闭合，不应借本轮错误分类修复声称 RRG 可用。
- 最新 publisher `23d8b20d` 成功但耗时 338.18 秒，其中 `document_index=121.37s`、`coverage_and_closure=92.93s`、`serialize=39.94s`，manifest 为 421,257,077 bytes。现有 document covering index 只优化了 `DocumentStore.status` 聚合；publisher `document_index` 可作为独立只读性能定位项，但它不是本轮数据合同缺口。

## 证据入口

- `docs/tushare-progress.md`：最新运行错误分类与 legacy Connect 接入状态。
- `docs/tushare-technical-extra-intake.md`：`cyq_chips` 权限、字段、历史范围和速率合同。
- `docs/tushare-field-coverage.md`：`research_report.file_name` 的官方文档冲突与留存样本。
- `backend/shared/tushare_intake.py`：供应商非零业务码的通用分类。
- `backend/shared/tushare_pipeline.py`：`api_error` 重试至 blocked、`empty_unverified` 终止逻辑。
- `backend/shared/tushare_text_contracts.py`：`research_report` required/extra 字段合同。
- `backend/shared/tushare_legacy_connect_contracts.py`：三个已接入 legacy Connect 合同与 planner。

