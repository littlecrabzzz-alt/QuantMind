# 全量分母、队列与磁盘只读检查
- Mac remaining_markets；本地 master `fef5233`；完成。接续 `20260908T215456Z-mac-fullscope-readonly-start-ada500a5.md`。仅本记录和 `/tmp` JSON；父修信用、text 接 PCF、structured 审互联互通，无重复改动。
- 云端采样 2026-09-08 21:57:08Z（北京时间 09-09 05:57）；仅 `dual-node.sh cloud-compose exec -T quantmind python3 -S -`，两个 SQLite 各自 `mode=ro` + `query_only` + 只读事务，另取白名单 JSON/文件元数据。未实例化 Pipeline、请求上游或读密钥。元数据与发布清单分开采样，不能视为全系统原子快照。

## 分母
固定目录 **263 条 + 11 条 discovered = 274 条文档义务**，另有 3 个未解析名称/领域引用（index_member、在岸人民币、私募基金）。263 不是 API 数：其中 36 条特殊页含分类/SDK/外部交付；基线去重接口名 227 个，排除 2 个账户 mutation 后自动采集名称 225 个。
代码已注册 **129 个 API / 129 个规范数据集身份**（RRG 7 + extended 122），均落在基线接口名中；名称层尚有 **96 个未注册**，不能把 129/263 或 129/225 当作历史覆盖完成率。6 个 VIP 财务 API 映射普通数据集名称，不能另算 6 个独立数据集。discovered 尚未增加运行注册；其中 rt_k/rt_etf_k 仅纯合同、pro_bar 为 SDK 派生，其他名称/正文缺口继续保留。
台账标签分布：planned 96、ingested_partial 70、implementing 53、review_required 36、permission_blocked 5、sample_empty_unverified 1、excluded_mutation 2；11 discovered 均 review_required。这些标签不是 SQL 完成量。

## 已规划任务（所有保存 epoch；计任务，不计行数或完整历史）
| family | pending | done | empty | quality | split_pending | 其他 |
|---|---:|---:|---:|---:|---:|---|
| credit_extra | 0 | 6 | 1 | 0 | 0 | — |
| equity_event | 11700 | 6 | 709 | 0 | 1 | — |
| futures_extra | 4856 | 153 | 197 | 0 | 2 | blocked 4 |
| global | 9656 | 564 | 1003 | 4 | 1 | blocked 5, deferred_legacy_period_plan 9802 |
| market | 8189 | 1451 | 2436 | 0 | 0 | blocked 3 |
| other | 287022 | 36 | 1330 | 2 | 4 | blocked 7 |
| research_extra | 10534 | 19 | 363 | 0 | 1 | — |
| rrg | 28865 | 11618 | 3365 | 3 | 0 | blocked 6 |
| structured | 7686 | 3820 | 20 | 5 | 0 | blocked 1 |
| supplement | 38146 | 1005 | 9 | 0 | 5 | — |
| text | 10453 | 2274 | 547 | 13 | 789 | resolved 205 |

合计 **458,902** 个任务：pending **417,107**、done **20,952**、empty **9,980**、quality **27**、split_pending **803**、blocked **26**、resolved **205**、deferred_legacy_period_plan **9,802**。split parent 与 child 同时留存，resolved/deferred 不能作为新增已采数据；empty 也不证明全历史为空。
全部 129 API 至少有任务；当前发布 Parquet 覆盖 **111 API**。其余 18 无已发布 Parquet：`cb_price_chg, cn_cpi, cn_gdp, cn_m, cn_pmi, cn_ppi, fut_wsr, hk_adjfactor, hk_daily_adj, index_weight, libor, sf_month, shibor_lpr, slb_len, stk_holdertrade, us_adjfactor, us_daily, us_daily_adj`。无 Parquet 不能统一归因于权限，包含空样本、未完成和明确拒权。
仅 4 个近期 planner 游标 done；9 个 history planner 均未完（当前 offset 3500），信用家族尚无 planner 游标且 `planning:credit_extra=validation_blocked`。有 9 个 unknown_history_bound、21 个 history_scope_unverified、37 个 coverage_unverified、33 个 discovery_unverified、7 个 row_cap_unverified 和 3 个 revision_coverage_unverified 能力记录；这是 gap 记录数，非 API 数。
权限拒绝 6 scopes：cb_price_chg、HK 复权因子/复权价、US 日价/复权价/复权因子；另有 hk_daily 已观察限频。global 当前只启用其 17 注册接口中的 12 个，保留既有拒权证据；信用修复由父处理。
最大待办：opt_daily **279,816（占 pending 67.1%）**，moneyflow_dc 29,759，fund_portfolio 27,935，fund_div 8,188。不能据数量降低其全历史义务；先检查规划粒度、已证明分页/日期分裂及公平调度，再优化请求效率。

## 附件与磁盘
附件队列：download pending **315,861**，retry **26**，blocked **154**；downloaded **790**，其中 parsed **746**、no_text 30、not_applicable 10、encrypted/parse_failed/parse_pending/parse_timeout 各 1。附件下载、解析和数据 API 队列是独立工作量，正文采集成功不代表附件闭包。
云端 Tushare 目录约 **19.873 GiB 逻辑量 / 20.123 GiB 文件分配量**（目录块未计；无重复 inode）；当前文件系统可用约 **299.430 GiB**。原始 API objects **4.918 GiB / 32,059 文件**，Parquet **1.534 GiB / 22,012 文件**，附件 **0.546 GiB / 1,012 文件**，提取正文 **0.020 GiB**。`documents` 索引/历史材料 **5.257 GiB**，`archives` **2.888 GiB**、`releases` **2.932 GiB**、validation **0.823 GiB**；这些不是新增市场数据行数。根文件（含 SQLite 等）另约 0.934 GiB。
当前发布 `data-9f873d8f67bf03b28c3777bb5da868fb38d78d18c4fb2ce91e610234172a43b1`（21:56:32Z）的 manifest 哈希匹配，清单 93,814 文件/15.177 GiB；历史与修订完整性均 false、RRG 仍 blocked_data。清单时间早于 live SQL，数目差异不等于丢数据。没有同口径两个可信时点，本轮不估队列增长率、最终磁盘量或全量 ETA。

## 影响 full coverage 的下一步（按当前障碍）
1. 父闭合信用历史代码发现/校验，恢复本来启用的规划；其余拒权/限频按现有证据单独处理，不能用 10100 积分推断都可调用。
2. 继续 96 个未注册基线接口与 11 discovered/3 未解引用审查；PCF 和互联互通按既有并行归属推进。区分类别、别名、SDK 派生、外部交付、分钟/实时独立权益，保留未知，不硬编一个封顶分母。
3. 闭合未知历史下界、主数据发现与退市集合，持续完成惰性 planner；重点核查 opt_daily 任务粒度，避免把当前 417k pending 当最终总量或重复创建第二采集队列。
4. 解开 803 个 split_pending（text 789），结合 row_cap/coverage gap 和 27 quality 做闭包验收；已出 Parquet 中仍有 possibly_truncated 1040、schema_gap 16 分区，不能仅计文件或 sample_ok 作历史完整证明。
5. 附件 315k 待办和解析异常单独验收；保留历史清单/附件闭包前提下评估索引/历史材料的磁盘效率，并由父按实际趋势按需扩盘。RRG 固定坐标消费已通过，不等这些全库工作完成才开发下一层。

详细证据：`/tmp/quantmind-fullscope-assessment-20260909.json`（含逐 API、family、gap scope、规划游标及字节量）；云端原始只读结果 `/tmp/quantmind-fullscope-cloud-20260909.json`，执行脚本 `/tmp/quantmind-fullscope-cloud-readonly.py`。未修改代码、运行配置、台账或数据。
