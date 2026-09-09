# limit历史月窗候选开始
- Mac remaining_markets；独立codex/tushare-limit-month-history，直接基于fafda74；concept纯e1041f2留原分支，不接runtime。
- 仅own backend/shared/tushare_limit_extra_contracts.py、scripts/test_tushare_limit_extra_contracts.py、docs/tushare-limit-extra-intake.md。近期7日仍exact day，历史月内范围；不改生产/队列/主planner。
- 只读现有path确认：intake cap/has_more→possibly_truncated→run split_request优先date_children→递归day→code fanout或blocked；不需新分片实现。
- 合同增加history_partition版本，让现有family合同fingerprint重置旧日offset，避免错用月序列。父确认limit4尚未enable/规划，拟在首次启用前验range再集成，现有其他队列不动。
