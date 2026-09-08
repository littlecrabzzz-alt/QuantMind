# ETF basket runtime ready

Owner text_contracts; isolated codex/tushare-text based on fef5233. Registry/store/mirror and bounded pipeline identifiers/planning/authorized normalize changes plus new test and existing PCF doc only. No production/config operations.

Family etf_basket registered; etfs discovery exclusively unions etf_basic raw source observations, including retired/special source codes; ordinary funds/stocks/cash basket components never enter it. Existing durable planners, gaps, date bisection reused; single ETF/day saturation and unknown unbounded history remain unresolved, permissions unprobed.

Mixed numeric/string source fields cannot fit one Arrow column: PCF contracted numeric columns now nullable text; per-row _raw_numeric_json contains exact original scalar types. Original immutable JSON and pre-conversion row hash retained. Arrow/JSONL/API returns text+provenance, not automatically decoded floats. Schema metadata source_scalar_encodings describes text_with_row_raw_numeric_json_v1; projections need provenance selected for exact original types. No generic conversion framework added.

Validation: new PCF pipeline 6/6, credit pipeline 6/6, extended pipeline 8/8; pure PCF prior 6/6. Ruff and diff check pass. Store extended 5/6 passes; only hardcoded total129 vs131 fails, parent owns updating count. Worktree clean after commit; parent can cherry-pick HEAD. All file ownership released.

Commit: ba898f8.
