# de494 固定版：`opt_daily` 之后的三项优先缺口

- 时间、节点、任务：2026-09-12 07:58:54 UTC，Mac，`/root/next_window_audit`
- 状态：完成，只读固定版审计
- 工作树：共享主工作树 `master` at `21c49a2d842101f50646f79bd853b530a956f6b6`；只新增本记录，未提交
- 输入：已提交的 `20260912T072800Z-full-scope-gap-audit.{md,json}` 和 Mac 只读固定镜像 `data-de494289775ece674a54bb560ac3ecad37187af6ed1ef69f8590b78ddbbb3fb0`
- 边界：未打开 live DB，未读凭据，未访问 Tushare，未修改代码、数据、authority 或服务

## 口径更正

`CURRENT.json` 指向 de494，对应 manifest 为 435,868,564 bytes，SHA-256 等于 release ID 后缀；它含 132,671 个 dataset 和 953,909 个文件。相比原全范围审计的 ce43，dataset 从 129,220 增加 3,451。有 dataset 的 API 仍为 194/244，capability API 仍为 224；`history_complete=false`、`historical_versions_complete=false`、`unimplemented_catalog_scope=true`、`rrg_status=blocked_data` 未变。

`opt_daily` 仍只有 18 个 `possibly_truncated` dataset；de494 覆盖为 empty 4,350、pending 1,204,390、quality 1、split_pending 17。这更正了 ce43 的 empty 4,289 / pending 1,204,451，不改变“先做已知非空合约-日精确样本”的结论。

## 排名建议

### 1. A 股核心市场六接口 exact wave

范围为 `daily` / `daily_basic` / `adj_factor` / `stk_limit` / `suspend_d` / `moneyflow`。de494 共有 1,523 个 `sample_ok` dataset，没有 `possibly_truncated` 或 `schema_gap`；待处理 71,008，empty 695，另有 `stk_limit` 1 个 normalize-timeout blocked。分项为：

| API | sample_ok dataset | pending | empty | blocked |
| --- | ---: | ---: | ---: | ---: |
| daily | 268 | 13,021 | 133 | 0 |
| daily_basic | 268 | 13,021 | 133 | 0 |
| adj_factor | 270 | 13,019 | 133 | 0 |
| stk_limit | 241 | 13,064 | 116 | 1 |
| suspend_d | 242 | 13,086 | 94 | 0 |
| moneyflow | 234 | 5,797 | 86 | 0 |

它们直接支撑 RRG 收盘价/复权、估值、可交易性和资金流分析；现有 `prepare_tushare_core_market_batch.py` + `run_tushare_core_market_batch.py` 已实现六 API 共同交易日、360 请求、固定 release/calendar/config/code SHA、pristine/attempt 与锁内 TOCTOU 复验。下一窗口只需按新 CURRENT 重新冻结和计划审核，无需新合同。

### 2. `index_daily` 继续精确历史批次

de494 已有 6,735 个 `sample_ok` dataset，无截断/字段质量项；覆盖为 done 6,735、empty 473、pending 143,024。相比 ce43 记录的 6,399 dataset / empty 432 / pending 143,081，数据叶 +336、empty +41、pending -57。它是 RRG 基准和行业指数收盘链路的直接输入；已有 `prepare_tushare_index_daily_batch.py` + `run_tushare_index_daily_batch.py` 以及 20 批零重叠证据。由于已连续做过 exact 批次，优先级低于尚未成规模的核心六接口 wave，但仍是无新代码的最稳妥后续。

### 3. `top10_holders` + `top10_floatholders` 持股人历史族

de494 已有 1,132 个 `sample_ok` dataset，无截断/字段质量项；两接口合计 pending 257,666、empty 618。分项为 `top10_holders` 567 dataset / pending 129,130 / empty 308，`top10_floatholders` 565 / 128,536 / 310。这更正了 ce43 的合计 1,084 dataset / pending 256,235 / empty 597；新 planner 展开使 pending 增长，不是回退。

现有 `tushare_equity_event_contracts.py` 和 `equity_event` planner 已固定 `ts_code`、报告期 `start_date/end_date`、完整字段及 distinct-row 语义，可用普通管线的有界 scope 开始。它们对持股集中度、股东变化和公司基本面研究有新增覆盖价值。当前没有专用 exact manifest/runner，而且官方数值 cap 和最早历史仍未验证；因此下一步应先用已存非空股票代码冻结一个小的年度报告期批次，不应直接将 257,666 任务视为已证明可完整排空。

## 未入选的高 backlog

- `moneyflow_dc` 已有 6,046 `sample_ok` + 125 `possibly_truncated`，pending 707,591 / split_pending 125；`dc_member` 已有 2,236 `sample_ok` + 470 `possibly_truncated`，pending 453,268 / split_pending 469。两者当前核心缺口是截断后代与历史 universe 证明，不是再加一轮普通 root 请求。
- `index_weight` 有 1,350 `possibly_truncated` dataset 和 91 blocked；已有专用后代闭环，但单日仍饱和的请求在供应商无分页/更细过滤证据前不宜加速重放。
- `research_report` 有 339 `schema_gap`，`anns_d` 有 1,209 个截断 dataset，`major_news` 有 815 个截断和 7 个 schema gap；已购文本权益仍有价值，但应先闭合字段/拆分合同，不与上述三项干净历史缺口抢同一窗口。
- `factor_value`、分钟/实时/港美权限族仍受单独权限、试用范围或已观察拒绝约束，不从 10100 积分或邻接 API 外推。

`fund_share` 作为后备执行项：de494 为 3,799 个全 `sample_ok` dataset、pending 20,972、empty 2,046，而且专用 exact runner 已成熟；但已完成 16 批，新数据族广度的边际价值低于持股人族。若下一窗口不允许增加专用持股人 runner，可将它作为第三顺位的零代码变更备选。

## 证据 pin

- de494 manifest：`~/Library/Application Support/QuantMind/tushare/releases/data-de494.../manifest.json`，435,868,564 bytes，SHA-256 `de494289775ece674a54bb560ac3ecad37187af6ed1ef69f8590b78ddbbb3fb0`
- 全范围审计 JSON：SHA-256 `21b3d2bbad8c5b091e9f25bf238980338191caed1a9193ea82c860c2c471bc36`
- core preparer/runner：`41e18f58e6dbc7ab7a021f423d129d4a2190f3a8bb31b0e0f386f936e3be7d09` / `b95026a04552ee0edf4c6b784b10ea629fa68d144f0b33f533a06592374b2ff3`
- index_daily preparer/runner：`1a24b23763fb0ca1e963fc908167d6b83bdd0608bd61c00a01b632feea09f832` / `edf06db0fb011c79122aa89585043ebee6a1843193c48b6390b390bf5013533d`
- equity-event contract：`c0b1a3b35d42511872d91779c5d029a7fbe64e33fd3d9a38364bfba8f5d954a8`

本记录是排名与后续窗口建议，不是任务冻结、执行授权、历史完整证明或 RRG 可交易认定。
