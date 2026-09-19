# Mac PDF parse retry recovery complete

- Node: Mac authoritative Tushare archive
- Runtime PID: `54716`
- Runtime root: `~/Library/Application Support/QuantMind/tushare`
- Fix commits: `f435a48d`, `28e60040`
- Production result: the legacy `parser_process_failed` set fell from 107 to 0 without restarting the active worker. Due parse retries also reached 0.
- Recovery cycle 1 (`2026-09-19T08:10:41Z`): 800 API requests and 1,702 document stages (873 downloads, 829 parses).
- Recovery cycle 2 (`2026-09-19T08:12:29Z`): 800 API requests and the configured 2,500 document-stage maximum (1,272 downloads, 1,228 parses).
- Remaining API queue after recovery cycle 2: 2,624,496 pending jobs. Full historical acquisition is still in progress.
- Disk: 1,793.28 GiB free; the 300 GiB hard reserve is active and the 500 GiB NAS migration warning is not active.
- Quality state: 331 jobs remain explicitly classified as the known `fut_rcpt_mat` or `fut_weekly_monthly` schema-gap cases; no new quality class was observed.
- Action: keep `com.quantmind.tushare-archive` running on the Mac as the unique full-archive writer. Do not restart it for stale status alone; verify the live PID, current database movement, and completed-cycle status first.
