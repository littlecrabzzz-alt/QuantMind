# Off-catalog eight-API bounded probe start

- Node/worktree: Mac isolated `/Users/lizeyu/.codex/worktrees/QuantMind-tushare-offcatalog-probe`; branch `codex/tushare-offcatalog-probe`; base `957d060b9e19a14125854239a7dc5a90c04980a3`.
- Scope: add only `scripts/tushare_offcatalog_probe.py`, its offline test, and coordination records for the eight merged default-disabled contracts.
- Boundary: dry-run by default; no production config/enable/publish, token read, authority access or upstream request in candidate work. Explicit execution must bind reviewed helper/contract hashes, verified `/data/tushare` authority, nonblocking shared `pipeline.lock`, schema 6, shared tiered rate gates and redacted raw evidence capture.
- Fixed budget: eight documented base calls plus at most three actual-row-derived filter calls; maximum 11 calls and 120 seconds; no retries, guessed filter values or fanout.
