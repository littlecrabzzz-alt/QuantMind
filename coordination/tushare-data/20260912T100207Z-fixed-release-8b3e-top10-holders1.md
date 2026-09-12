# Tushare 8b3e fixed release closes top10 holders batch 1

- The normal hourly publisher task `22cb2814-b719-4f70-8642-9829beac5ba2` completed in 383.078 seconds with `publish_only` and zero upstream calls. It atomically published `data-8b3e0b4a4937bb57830be68272ea19d4fa812310561e7a58b3eddb039b71d2c7` with a 446,611,290-byte manifest, 974,260 files and 135,013 datasets.
- The first 180 `top10_holders`/`top10_floatholders` sibling pairs contributed 944 reviewed references and 3,168,798 bytes: 360 raw objects, 360 observations and 224 Parquet files. Cloud verification found zero missing references, manifest metadata errors or physical SHA errors.
- The standard Mac LaunchAgent was idle and started without `-k` as run 271. It downloaded 4,444 files, verified all 974,260 manifest entries, exited zero with empty stderr and atomically switched local `CURRENT.json` to the same release.
- The same exact verifier passed all 944 references on Mac. Cloud and Mac verifier reports are byte-identical with SHA-256 `f48f1f18d2648cb51c6455f7c7b8bc679ae59a35b5f23cebb48ba5a3a7eccfe6`.
- In the production image with Docker network disabled, socket/DNS/secret guards, empty Tushare token variables and a read-only mirror, `top10_holders` and `top10_floatholders` each returned three local rows and 15 columns. Upstream calls were zero.
- All five services remained running with restart count zero and no OOM. QuantDB was not stopped. Cloud storage had 329,013,694,464 bytes free, 221,639,512,064 bytes above the 100 GiB reserve.

This closes only the reviewed batch at `end_date=20071231`. Complete holder history, empty-result completeness, source revisions, intraday known_at, PIT ownership, later periods and RRG/strategy claims remain open. Machine evidence: `docs/tushare-fixed-release-8b3e-top10-holders1-20260912.evidence.json`.
