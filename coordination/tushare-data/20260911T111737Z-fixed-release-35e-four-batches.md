# Fixed release 35e closes four post-8f6 batches

- Normal publisher task `ee1b7011-13cf-4919-bf16-d28b187787e3` completed with Celery SUCCESS and zero upstream requests. It atomically published `data-35e0779328370f69b74d06208f4755d53eb71c1efa57d209197c56d6e1ca1421` in 190.792 seconds: 112542 datasets, 832233 files and a 331919013-byte manifest whose SHA256 matches CURRENT and includes retained observations.
- Mac LaunchAgent run 195 downloaded 8312 files, verified the full 832233-file manifest, wrote zero stderr bytes, exited 0 and atomically switched CURRENT.
- The four frozen manifests contain 1320 jobs. Their 1077 terminal leaves resolve to 3121 unique references: 1077 objects, 1077 observations and 967 Parquet files totaling 28848540 bytes. The fixed-release verifier passed all manifest metadata and local SHA256 checks with zero missing or corrupt references.
- The production image read `index_daily`, `fund_daily`, `fund_adj`, `fund_share`, `income_vip`, `balancesheet_vip` and `cashflow_vip` with `--network none`, socket/DNS guards, empty Token variables and a read-only mirror; each returned three rows and upstream calls were zero.
- The 243 pending leaves remain explicit: 24 in fund price batch 14 and 219 in financial batch 19, including two separately recorded ReadTimeout attempts. The regular exact cap remains 300 requests per 90-second window.
- Cloud free disk is 221457752064 bytes, leaving 114083569664 bytes above the 100 GiB reserve. QuantMind, Tushare Worker and Beat are healthy.

Machine evidence: `docs/tushare-fixed-release-35e-four-batches-20260911.evidence.json`. Complete history, revisions, `known_at`, PIT membership, RRG tradability and PCF remain open.
