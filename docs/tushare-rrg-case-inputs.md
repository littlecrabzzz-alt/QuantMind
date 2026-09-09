# 固定 Tushare 输入到 RRG 研究文件契约

`prepare_tushare_rrg_case_inputs.py` 复用坐标验收使用的 `read_dataset`，要求已经通过的坐标报告及其显式 SHA。它不重复调用行业审计或坐标算法，仅核对报告、原固定 release 和配置，映射到现有 `research_case` 的两个输入 glob。原研究脚本/config 当前可作为外部文件，只读其路径/哈希和字段契约；不复制、导入或提交它们。

独立新目录包含：

- `data/quantdb/1_kline_data/index_daily/tushare_rrg.parquet`：保留原始存储列，新增 `IndexCode=ts_code`、`time=trade_date`、`Category=中信一级`。该分类标签只表示已冻结的审计清单，逐行 `classification_verification=frozen_audit_scope_only`，不证明官方历史分类。保留观测来源与价格固定 release ID。
- `data/quantdb/2_base_sector/trading_calendar/trading_days.parquet`：SSE 日历映射为 `TradingDate`、`IsTradingDay`，保留原列和各行来源 release。原比较窗口之外的补充来自单独显式固定版，最多 31 天；缺日/冲突拒绝，不猜交易日。
- `input-report.json`：精确查询、输入/脚本哈希、来源分区、下一开市日映射及各层缺口。日历映射不代表该开盘价格或可成交性已验证。
- `manifest.json`：上述三个文件的字节数和 SHA。输出必须为仓库与源数据目录之外的新目录，不跟随 CURRENT，不覆盖旧 case，不修改研究状态。

未准备的历史成员及 ETF 文件明确列入 `unprepared_datasets`；不生成假的 `known_at`、历史行业版本、持仓暴露或交易状态。所有语义门槛保持 `unknown`，输出固定 `blocked_data`。它是可交给研究工作流进一步审查的输入目录，**不是已经注册/通过的 research_case**；注册源码存档、后续语义评审与策略执行不在本脚本内。

已有独立切片/坐标依据见 [坐标验收](tushare-rrg-coordinate-acceptance.md)。实际可复跑示例（输出改为不存在的新目录）：

```bash
UV_OFFLINE=1 uv run --no-project --with httpx --with pyarrow --with duckdb python -B scripts/prepare_tushare_rrg_case_inputs.py \
  --root '/Users/lizeyu/Library/Application Support/QuantMind/tushare' \
  --release-id data-6e00837911a40223d75d7e4e7b770b4b60b4b7c9f2d208091c6e343f7283bee6 \
  --config '/Users/lizeyu/Documents/ChatGPT/投资/QuantMind/config/rrg_sector_rotation.json' \
  --coordinate-report /tmp/quantmind-rrg-coordinates-20260909-final/report.json \
  --report-sha256 f6918cc7d445ba4e8c3745c3f830dfc86ce272ee8151cb272647ae24145e5f60 \
  --calendar-release-id data-e1386fc1f304f2ef6ef34d3c59ec99b4f3d1ec34fd49c9841ddd7591a74e1bce \
  --calendar-end 20260901 \
  --research-case '/Users/lizeyu/Documents/ChatGPT/投资/QuantMind/scripts/research_case.py' \
  --output /tmp/quantmind-rrg-case-inputs-review-new
```

运行期间禁止 socket/DNS 和密钥读取；没有上游回退。输出价表包含 28 行业的 36,008 行，日历 1,934 行；48 个月末均映射到下一开市日，最后一项为 2026-08-31→2026-09-01。原始价格/日历审计和算法测试没有重跑，报告只沿用已验收依据。

专项隔离测试验证来源列、原文哈希、两版日历映射、不生成 known_at/研究状态、错误报告或配置、缺日/旧映射变化，以及输出覆盖/源目录写入拒绝。输入或外部研究契约变更时须用新报告与新输出，不放宽指纹校验。
