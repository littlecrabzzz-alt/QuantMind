# Fixed release 266b closes three post-35e work units

- Normal publisher task `bd37f156-1024-4017-8190-6bf74c51d670` completed with Celery SUCCESS in 150.557 seconds and zero upstream requests. It atomically published `data-266bb56dfb9fbf5c8f55d623d7258f1c8c51d096d1a8af117f2779679257c2c2`; the 336067672-byte manifest has 113637 datasets and 837205 files, includes retained observations, and hashes to the release ID.
- Mac LaunchAgent run 199 downloaded 4971 incremental files, verified all 837205 manifest entries, wrote zero stderr bytes, exited 0 and atomically switched local `CURRENT` to the same fixed release.
- The fixed-release verifier passed all 2414 exact references from fund price batch 15, the 218 financial recovery jobs and index daily batch 8: 818 objects, 818 observations and 778 Parquet files totaling 22883575 bytes, with zero missing, metadata or local physical errors.
- The production image read seven relevant APIs from the read-only Mac mirror with Docker network disabled, socket and DNS guards, and empty token variables. Each returned three rows and upstream calls remained zero.
- API, Tushare Worker and Beat remain healthy. Cloud free disk remains 113434681344 bytes above the 100 GiB reserve.

These three work units are now locally usable without Tushare Pro. Complete history, revisions, `known_at`, PIT membership, RRG tradability and PCF remain open. Machine evidence: `docs/tushare-fixed-release-266b-three-work-units-20260911.evidence.json`.
