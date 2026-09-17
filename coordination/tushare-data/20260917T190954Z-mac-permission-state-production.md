# Tushare permission state maintenance production result

- Code: `9175461a0c21b18f9e9bb6b9c22734b6b0d200b6` on master and origin/master.
- Tests: 54 focused and adjacent tests passed; Ruff, `py_compile`, and `git diff --check` passed.
- Isolated production backup: 37 jobs reclassified, 37 results and 38 attempts retained byte-for-byte, second run `no_action`, SQLite `quick_check=ok`.
- Production: planning capability `planning:permission_state_maintenance=applied`; `blocked` 910 -> 873 and `permission_blocked` 4,657 -> 4,694. The migration made zero Tushare calls.
- Runtime: drained after the cycle ending `2026-09-17T19:06:11Z`, installed matching source hash, restarted as PID 62693.
- Real acceptance: cycle `2026-09-17T19:07:54Z` to `19:09:35Z`, 384 provider requests, 100.714 seconds, no failed stage, stderr 0 bytes.
- Receipt: `validation/permission-state-maintenance-v1.878e8decce83ac421d674a9da29f9674a9e3ebddc879f0e5c6332d7d01dd7440.json` under the Mac archive root.
- Boundary: published manifests continue to expose these as permission gaps and keep `history_complete=false`; no data completeness claim changed.

