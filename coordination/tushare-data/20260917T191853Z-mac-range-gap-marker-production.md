# Tushare range replacement gap marker production result

- Code: `eb6678b01078c40b8e53781edcb9f1c0ab39301f` on master and origin/master.
- Tests: 16 focused and adjacent tests passed; Ruff, `py_compile`, and `git diff --check` passed.
- Isolated production backup: exact 762 replacement parents restored, 762 results and 762 attempts preserved, second run `no_action`, SQLite `quick_check=ok`.
- Production: exact 762 parents now retain `status=blocked`, `gap=replaced_by_stock_range_plan_v1`, and the durable evidence marker. One separate `dc_member` parent with live children remains a genuine unresolved partition.
- Runtime: drained after the cycle ending `2026-09-17T19:16:39Z`, installed matching source hashes, restarted as PID 68097.
- Real acceptance: cycle `2026-09-17T19:17:12Z` to `19:18:53Z`, 387 provider requests, 101.002 seconds, no failed stage, stderr 0 bytes.
- Receipt: `validation/range-replacement-gap-repair-v1.c4c6dec171da3a13bc2e56e012079e6890e8c16488cf536149c9b6204281bba9.json` under the Mac archive root.
- Boundary: blocker totals remain `blocked=873` and `permission_blocked=4,694`; this restores the reason for 762 preserved blockers without claiming their replacement ranges are complete.

