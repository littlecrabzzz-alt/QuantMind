# NPR capped-history recovery start

- Owner: Mac archive integration task
- Scope: `backend/shared/tushare_pipeline.py`, `backend/shared/tushare_text_contracts.py`, and focused Tushare tests in branch `codex/tushare-npr-saturation`.
- Production acquisition remains active. Candidate work uses a temp-only pipeline database and no credentials or upstream requests.
- Goal: map retained NPR `puborg` observations to the documented `org` request parameter, recover the two legacy capped parents with zero upstream calls, preserve unknown-organization and terminal exact-second gaps, then merge, install, and verify real production progress.
