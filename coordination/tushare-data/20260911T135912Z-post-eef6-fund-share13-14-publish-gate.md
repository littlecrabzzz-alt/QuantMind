# Post-eef6 fund_share batches 13 and 14 publication gate

- The cloud authority has 660 terminal jobs from the two new `fund_share` batches: 455 done and 205 empty. Their clean 300- and 360-request windows made 660 HTTP 200 calls with zero uncertain calls.
- After a no-revoke drain, an exclusive-lock, query-only export recomputed all physical hashes. The inventory contains 1775 unique references: 660 objects, 660 observations and 455 Parquet files, totaling 12225439 bytes. The 320162-byte inventory SHA256 is `7c7e91138926186566fad96f147950fc482f5f745b1cd210a1dd2cab7bc72fab`.
- Mac remains on fixed release eef6. The persistent verifier produced the required negative control: all 1775 references are absent from the old manifest, with zero metadata or local physical errors and exit 2.
- The first wrapper used zsh's reserved `status` variable after running the verifier; rerunning with `verify_rc` captured the expected exit code. A separate capacity probe first used a relative SQLite URI and was repeated with an absolute read-only URI. Neither event changed cloud or Mac data.
- API, Tushare Worker and Beat are healthy. The cloud volume remains 112483012608 bytes above the 100 GiB reserve. The normal publisher becomes due after 2026-09-11 22:19:26 CST.

Next: allow the normal publish-only path to create a new immutable release, run the standard one-way Mac mirror, positively verify all 1775 references and repeat no-network, empty-token, read-only `fund_share` access. Machine evidence: `docs/tushare-post-eef6-fund-share13-14-publish-gate-20260911.evidence.json`.
