# Mac application archive reader mount prepared
- Mac, UTC 2026-09-16 17:59; migration ongoing.
- master/codex/mac-data-source 4058cdda: quantmind local Compose supports QM_LOCAL_TUSHARE_ROOT with original sandbox/data/tushare default, mounted read-only at /data/tushare. Other /data remains the sandbox writable mount. No actual .env.local change or container recreation yet.
- Actual docker compose config verified default and override path (including spaces), read_only=true, and unchanged writable sandbox /data. Documentation requires full archive/fixed-version acceptance before selection and an idle local task window for stop/start recreation; child research inputs remain pinned independently.
- Full precopy PID 61325 / receiver 61393 remains active, now objects/56...; documents and extracted phases have been traversed. Eleven frozen databases are all hash-verified from previous turn, no prestage running.
- Next: finish precopy then sync-frozen, install/finalize, native worker activation; production readers still require actual cutover/queries and cloud cleanup stays gated on complete data proof.
