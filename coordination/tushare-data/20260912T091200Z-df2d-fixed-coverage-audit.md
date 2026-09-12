# Tushare df2d fixed-release coverage audit

- The audit ran entirely against the immutable Mac mirror at `data-df2dceada681d30b2d4c24c7df5877452c5d27f2479557b493378d7f4ec3f7ff`; it made no upstream call and did not mutate authority data.
- Current code registers 246 read interfaces. The normal fixed-release scope contains 244; the two intentional exceptions are account-private `p_list` and `p_get`, which remain default-disabled from ordinary planning.
- 194 registered interfaces have at least one published dataset. Fifty planned interfaces do not. The initial direct-capability-only grouping below was superseded by the retained-gap-aware correction in `20260912T092136Z-df2d-coverage-evidence-classification.md`: 37 have `permission_denied` evidence, 11 have `api_error` evidence, and two (`stk_alert`, `stk_high_shock`) are available but only have retained empty observations.
- The 50 are explicit gaps rather than an omission count. Independent minute/realtime permissions, deterministic contract blocks and successful empty responses require different follow-up and must not be converted into fake datasets.
- Full report: `docs/tushare-df2d-coverage-audit-20260912.json`, SHA-256 `a46e1b651f6627b68c9f7157f83553eb725e45da3b81419ccb7539f125cf1cbd`.

A published dataset still does not prove complete history, revisions, fields, attachments or point-in-time validity.
