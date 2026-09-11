# Financial batch 19 pristine recovery

- Commit `0bfd32fe` adds a recovery manifest generator for existing financial exact manifests. It selects only source tasks that remain pending with zero attempts, records source lineage and recomputes the task inventory hash. Pending tasks with attempts are rejected by default or explicitly excluded; execution rechecks pristine state under the exclusive authority lock before credential or upstream access.
- Mac and production Python 3.10 each passed all 13 targeted tests. Python compilation and diff checks passed; Ruff is absent from both available runtimes and was not installed during production work.
- From batch 19, an income/balance submanifest recovered 145 pristine leaves in 20.399 seconds and a cashflow submanifest recovered 73 in 10.228 seconds. All 218 requests returned HTTP 200; the recovery added 212 done and 6 empty states with zero uncertain calls.
- The original 360-job batch now has 353 done, 6 empty and one pending task. The sole pending task is the earlier cashflow ReadTimeout and remains isolated without replay. Across the 359 terminal leaves, 359 objects, 359 observations and 353 Parquet files form 1071 unique references and 14250009 bytes; all physical SHA256 checks passed.
- The first closure assertion used the wrong status label for valid empty responses. Read-only diagnostics showed `empty_unverified`; the assertion was corrected before any closure write, without replaying upstream calls or modifying the authority database. Worker and Beat are healthy after restore.

Machine evidence: `docs/tushare-financial-pit-batch19-recovery-20260911.evidence.json`. The 1071 references await normal fixed publication and Mac mirroring; complete financial history, revisions, `known_at` and PIT coverage remain open.
