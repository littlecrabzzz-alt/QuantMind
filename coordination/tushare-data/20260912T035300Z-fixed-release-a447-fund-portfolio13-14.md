# Tushare fixed release a447 and fund_portfolio batches 13-14

- The normal publisher task `d4ae2b37-1e72-4eed-8eb1-e243f1b06771` completed with Celery SUCCESS in 226.209 seconds, publish-only and zero upstream calls. It atomically switched cloud `CURRENT` to `data-a4475b3a…`.
- The 366,014,060-byte content-addressed manifest has 118,258 unique datasets and 869,194 files with retained observations. Independent verification found zero dataset-path, file-metadata or manifest-hash errors.
- An immutable-observation inventory rebuilt all 480 batch13/14 responses and 1,235 physical references (480 object, 480 observation, 275 Parquet), 3,784,023 bytes. Every cloud file SHA passed and every reference appeared in a447 with matching metadata.
- The standard Mac LaunchAgent run 225 downloaded 4,085 incremental files, verified all 869,194 files, emitted zero stderr, exited 0 and atomically switched at 03:48:35 CST. Independent Mac verification found zero missing, metadata or physical errors for all 1,235 references.
- A production reader then returned three `fund_portfolio` rows and 15 columns from a447 with networking disabled, socket/DNS guards, empty tokens, source/code mounts read-only and zero upstream calls.
- Worker and Beat are healthy with restart count 0 and OOM false; normal acquisition resumed. Cloud storage retains 410,330,341,376 bytes above the 100 GiB reserve.

Batches 13-14 are now available locally without Tushare. Complete holdings, daily PCF, source revisions, intraday `known_at`, PIT membership and authoritative ETF-industry mapping remain open. Machine evidence: `docs/tushare-fixed-release-a447-fund-portfolio13-14-20260912.evidence.json`.
