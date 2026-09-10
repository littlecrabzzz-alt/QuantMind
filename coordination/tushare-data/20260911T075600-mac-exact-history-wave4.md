# Tushare exact history wave 4

- Owner: Mac controls the bounded run; the cloud authority is the only formal writer.
- Safe drain: Celery Beat stopped first, the exact `tushare_acquire` consumer stopped accepting new work, and task `c3bb96f6…` completed naturally in 186.776 seconds. Active and reserved work were empty before the dedicated worker stopped. No task was revoked.
- Frozen input: all four immutable manifests reference fixed release `data-bdb8d5c76f676b5595a8af871cbc563e3705ff25713c4a5514c61b9aca9e6b68` and authority configuration `da45afae…`.
- Plan-only: every batch reported false for authority, credential, network, write, and publish access before execution.
- Result: 904 upstream calls, 904 HTTP 200, 0 HTTP 429, 1,315,020 rows. Physical SHA verification passed for 904 raw objects, 904 observations, and 904 Parquet files. Authority closure SHA-256 is `c7863997652553170b7fc051d9a61c61f5ed09bd94d7b06d612bde5effd5d143`.
- Fund price batch 5: 360/360 done in 43.860 seconds, 240,136 rows across `fund_daily` and `fund_adj`, covering 2017-01-18 through 2017-10-17.
- Dividend batch 4: 360/360 done in 44.779 seconds, 22,402 rows, selected evenly from Shanghai and Shenzhen.
- NPR history leaf batch 2: four newly created leaves completed in 1.785 seconds; two became done and two split again, returning 1,014 rows.
- Announcement batch 3: the manifest froze 360 tasks, while the execution cap was reduced to 180 calls. It completed 180 HTTP 200 calls in 63.277 seconds, yielding four done, 176 split-pending, 180 untouched pending tasks, and 1,051,468 rows.
- Restore: the dedicated worker and Beat are healthy with zero restarts and no OOM. The API remains healthy. Cloud free space is 232,403,939,328 bytes, above the 100 GiB hard reserve.
- Publication boundary: `CURRENT.json` remains `data-bdb8d5c7…`; wave 4 and both NPR residual batches are authority-only until the next hourly fixed publication, due no earlier than 08:17 CST. The Mac mirror may advance only after that atomic cloud publication.
- RRG audit: current industry price and calendar coverage is already high. The primary blocker is still PIT industry classification and member versions with `known_at`, revision, and source evidence; additional price volume alone does not remove `blocked_data`.
- Capacity item: the whole-project snapshot timer remains disabled until cloud disk expansion and peak-headroom validation. Tushare acquisition, publication, and Mac mirroring continue.
- Boundaries: `history_complete=false`, historical revisions are incomplete, `pit_verified=false`, and RRG remains `blocked_data`.
- Machine evidence: `docs/tushare-exact-history-wave4-20260911.evidence.json`.
