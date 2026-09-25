# R01 数据合同（data-contract）

- 版本：v2.3（R01P0-F1C1 修订冻结，2026-09-25T02:00:00Z；AC-01 分红三日期事件结构，配套 schema v3/包版本 v2。v2.2 见 REVISION.md）
- 状态：**冻结**。变更须在主工作树 `coordination/r01-p0/` 追加记录并出合同新版本。
- 对齐：平台设计 §4；机器 schema（单一来源，三份合同互引不重复定义）：`data-contract.schema.json`（回报信封）、`etf-input-package.schema.json`（输入包 manifest+typed events）、`readiness.schema.json`（准入对象）。
- 命名规范：字段一律 snake_case；`project_key` canonical 值为小写 `r01`（展示名 R01 仅用于 UI）；来源标识统一 `source_task`；`contract_hash` = 所引版本合同文件 UTF-8 字节的 sha256。

## 1. 公共字段（外部回报信封）

字段表与约束以 `data-contract.schema.json` 为准（required 集合含 `source_task`）。要点：

| 字段 | 说明 |
| --- | --- |
| schema_version | =2 |
| project_key / workstream | `r01`；workstream ∈ P0/A/B1/B2/B3/D/N |
| case_id / source_task / source_run_id / event_id / seq | 幂等与乱序校验五元组（见 report-api.md §3-§4） |
| strategy_id | 策略定义标识；P0 工程样例必须 `fixture-` 前缀 |
| contract_version / contract_hash | 本合同版本与文件哈希 |
| source_node / source_revision | 来源节点与代码提交 |
| data.input_package_id / data_as_of | 固定输入包与数据截止日 |
| timestamps.source_at / received_at | 来源时间与平台接收时间**分开**；received_at 由平台写入，存储态必填 |

## 2. 两套状态与 fixture 约定

1. **执行状态** execution_status：`planned / running / blocked / failed / completed / stale`（断联=stale，不算失败也不算成功）。
2. **证据阶段** evidence_stage：`proposal / data-check / development-compare / engineering-validation / independent-verification / forward-observation`。`engineering-validation` 专用于 P0 工程验收；完成代码作业不自动提升证据阶段。

**P0 工程样例命名与标注约定**（schema 强制）：`fixture=true` 且 `strategy_id` 以 `fixture-` 前缀（如 `fixture-risk-line-demo`）；展示层必须渲染显著"工程样例 (fixture)"徽标，与真实研究曲线、收益排行、月报隔离；fixture 曲线不得与真实曲线同图无标注混排。

## 3. ETF 固定输入包接口（TG-007 裁决，p02 生产 / p03 消费）

### 3.1 来源与版本
- 唯一来源：Mac Tushare 归档，按 **release_id** 固定读取（首发 `data-fcbabbb7f133dddab1109d3c130653b46041e2c9f6c9cd53b685d3d28f8ac0ab`）。换 release ⇒ 新 `package_version` 并记 decisions。
- 数据集：`fund_daily + fund_adj + fund_div + trade_cal + etf_limit`（etf_limit 2019-06-26 起；不足段 ±10% 规则近似并在 known_gaps 声明 `rule-approximation-declared`，DG-004）。
- 禁止：研究直接读归档 CURRENT；与 QuantDB `etf_kline` 裸拼接（DG-002/DG-009/DG-010）。

### 3.2 位置：节点受控引用（不写裸绝对路径）
- 包的逻辑引用：`node://<node>/r01-etf-daily/<package_version>`（manifest.package_uri）。
- 各节点把 `package_id` 解析为本地绝对路径的**节点私有注册表**：Mac 为 `~/Library/Application Support/QuantMind/r01/package-registry.json`（P0.2 v1 实现口径）；注册表及其快照必须进 P0.5 交接包（W1R2 第 6 项条件），否则独立验收只能验哈希不能复现文件位置。
- 消费方（p03 LocalMarketData ETF 视图）凭 `package_id + manifest_sha256` 校验后只读挂载；校验失败显式报缺口，不静默降级。

### 3.3 目录布局与机器 schema（v2.2：与 P0.2 生产者 / P0.3 消费者实际实现一致）

实际布局（生产者 `scripts/prepare_r01_etf_inputs.py` docstring 与写出代码；消费者 `backend/services/simulation/replay/etf_input_package.py` 只读视图同口径）：

```
<output-root>/<version>/
  manifest.json                # 必须通过 etf-input-package.schema.json
  SHA256SUMS.txt               # 包内其余每个文件的 sha256
  README.md                    # 布局、换算规则、预热与使用说明（包内生成）
  derivation-report.json       # 证据：覆盖、事件、fund_nav 交叉核验
  calendar.parquet             # SSE 交易日历：exchange, cal_date, is_open, pretrade_date
  daily/<code>.parquet         # 未复权日线：ts_code, trade_date(YYYYMMDD),
                               #   open, high, low, close, pre_close,
                               #   vol_shares(份), amount_cny(元)
  factors/<code>.parquet       # hfq 复权因子：ts_code, trade_date, adj_factor
  dividends/<code>.parquet     # 原始 fund_div 事件（仅有分红的标的）：
                               #   ts_code, ex_date, base_year, div_cash 等
  events/<code>.parquet        # typed 公司行动（仅有事件的标的）：平铺列
                               #   event_date, event_type, cash_per_share,
                               #   qty_multiplier, adj_factor_prev, adj_factor_new
                               #   （schema $defs.typed_event 的 derived_from 为平铺列）
  etf_limit/<code>.parquet     # 交易所涨跌停价（2019-06-26 起）：ts_code,
                               #   trade_date, pre_close, up_limit, down_limit, asset_type
```

- `<code>` 一律 suffix 式（`510300.SH`）；全链路禁止依赖裸六位自动识别（XG-001）。
- 单位换算在包内完成：`vol_shares = fund_daily.vol×100`、`amount_cny = fund_daily.amount×1000`，规则同时记录于 manifest.unit_conversions（DG-009）。
- **无 `tradable` 列**：可交易性不在日线中物化，按 DG-004 口径由消费侧推导（缺行=数据洞 vs 停牌分开记录；零成交日；etf_limit 涨跌停价；2019-06-26 前无 etf_limit 行的时段由消费侧 ±10% 规则近似并在 manifest.known_gaps 以 `rule-approximation-declared` 声明）。
- 工程 fixture 包允许另一套列口径（trade_date YYYY-MM-DD、volume 手、amount 千元、adj_factor 内联），仅用于工程验收（consumer 自动识别）；真实研究输入一律用上述真实包口径。
- 订正说明：v2 原文误写 `symbols/`、`limits/` 目录名，且未列 `factors/`、`dividends/`、`SHA256SUMS.txt`、`README.md`、`derivation-report.json`；实际生产/消费自始使用 `daily/`、`etf_limit/` 等上表布局。本次订正不改变接口语义、单位、事件规则与哈希校验（见 REVISION.md attempt4）。

### 3.4 typed 公司行动：定义与时序（DG-005 裁决；分红字段 AC-01/F1C1 修订）

**因子约定（normative）**：`adjusted_close = close_unadjusted × adj_factor`（hfq）。每个 `adj_factor` 跳变日必须归类（schema 二选一）：
- `cash_dividend`：与 fund_div 对上；`cash_per_share>0, qty_multiplier=1`；**必填分红三日期与权益基准**：`record_date`（登记日，权益基准=收盘在册持仓）、`event_date`（=ex_date 除息日）、`pay_date`（发放日）、`entitlement_basis="record_date_close_holdings"`、`event_id`。record/pay 未知时必须显式 `record_date_status/pay_date_status="unknown_blocked"`（对应日期为 null），禁止默认 ex_date；blocked 事件须 `verification.method=unresolved_gap, passed=false`。三日期语义约束（validator 语义层校验）：`record_date ≤ ex_date ≤ pay_date`。
- `share_adjustment`：无现金事件的因子跳变（拆分/份额折算）；`cash_per_share=0, qty_multiplier = adj_factor_new / adj_factor_prev ≠ 1`；不得携带分红日期字段。
- **验证公式**（p02 对每个事件执行，写入 verification）：价格连续性 `close_ex ≈ pre_close_ex × (adj_factor_prev / adj_factor_new)`（无现金事件时），价值守恒 `qty_new × close_ex ≈ qty_old × close_prev`；fund_nav 可得时交叉验证；分红三日期以交易所/基金公告为准（`derived_from.fund_div_ref` 必填公告引用，如 511090 2024-04-19 上交所披露 PDF）。无法归类、验证不过或日期缺失 = **显式缺口**（`unresolved_gap`），禁止按零处理。
- 强制回归用例：`159934.SZ 2025-09-22`（qty_multiplier=0.9481）、`510500.SH 2015-04-15`（qty_multiplier=0.2803）、`511090.SH 2024-04`（record 04-23 / ex 04-24 / pay 04-29，1.5 元/份，AC-01 三例见 ledger-contract §6）。

**账务处理时点**（ledger-contract §5/§6 消费）：
- `share_adjustment`：event_date **开盘前、当日任何订单撮合之前**调整持仓数量。
- `cash_dividend` 三段式：record_date EOD 按收盘在册持仓定格资格 → ex_date 开盘前入 `dividend_receivable`（计入 nav，不可交易）→ pay_date 开盘前转可用现金。**禁止 ex_date 当日交易后持仓发放**（AC-01 废弃语义）。
- 同日两类并存：先份额调整（开盘前），cash_per_share 已是调整后份额口径；资格定格不受当日份额调整影响（record 先于 ex）。
- 幂等键：分红 `(ledger_run_id, symbol, event_id, entitlement_date=record_date)`；份额调整 `(ledger_run_id, symbol, event_date, event_type)`。

**包版本约定**：schema v3（`schema_version=3`）⇔ **包版本 v2** 起；**v1 包**（schema_version=2 事件结构，无分红三日期字段）保留只读：按 `archive/etf-input-package-v2.schema.json` 校验，其分红语义已废弃，不得用于权益资格计算（见 handover/ASSUMPTIONS-DEFERRED.md）。

## 4. 数据检查项
每项 `passed / failed / unknown` + 证据引用；`unknown` 不得当 `passed` 展示（schema checks[]）。

## 5. readiness.json（准入对象）
机器 schema：`readiness.schema.json`。要点：四类 ready 布尔 + `blocking_gaps[]`（引用 gaps.json id）+ `evidence_refs[]` + `input_manifest`/`etf_input`（节点受控引用，含 manifest_sha256）+ `contract_versions` + `self_check_at` 与 `independent_acceptance` 分开。P0 自检与独立验收分开记录；研究启动入口与外部结果准入处必须检查本对象；未准入的外部产物保留原始回报并标记未准入。数据或代码影响结论的变化 ⇒ 重新核验相关项；缺口删除/降级须说明范围变化。

## 6. 结果绑定与新闻覆盖
- 指标（metrics[]）：`value=null` 时必填 `null_reason`（not-computed / no-data / not-applicable / pending-verification），不得填 0；绑定金额、时期、价格/费用口径与策略版本（basis）。
- D/N 组回报**必填** `news_coverage.decision_cutoff_at`（决策截止）与 `news_obtained_at`（新闻实际取得时间）（schema allOf 强制）。
- artifact 引用统一 `artifacts[].uri`（`node://<node>/...` 或课题相对路径）+ sha256；前端消费统一本 schema 类型，A/B 不各写一套 JSON。
