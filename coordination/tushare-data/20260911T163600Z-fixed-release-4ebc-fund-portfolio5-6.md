# fund_portfolio batches 5/6 fixed-release closure

- The ordinary publisher resumed after QuantDB recovery and created `data-4ebc1a70135cb6e08fd718d6aea19e4480d293da3e0fe39e82b9c22f1e3b0b22` with zero upstream requests. Celery state was `SUCCESS`; the manifest contains 116286 datasets and 856556 files.
- The standard Mac LaunchAgent run 214 downloaded 5507 incremental files, verified the complete release and exited 0. The exact verifier found all 1284 references and 6065292 bytes from fund portfolio batches 5 and 6, with zero manifest, metadata or local physical errors.
- The production base image read three `fund_portfolio` rows and all 15 columns from the read-only mirror with no network, socket/DNS guards and empty Token variables. Upstream calls were zero.
- Cloud data storage is 845309321216 bytes with 520229150720 bytes available. General, research and Tushare workers plus Beat are healthy; the whole-project snapshot timer is enabled and active for 07:00 CST.

This closes immutable local availability for these two batches. Complete holdings history, daily PCF, supplier revisions, `known_at`, PIT membership and authoritative ETF-industry mapping remain open. Machine evidence: `docs/tushare-fixed-release-4ebc-fund-portfolio5-6-20260912.evidence.json`.
