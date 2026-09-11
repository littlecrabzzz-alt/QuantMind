# Fixed release 8f6 closes three post-79a2 batches

- Normal publisher task `9f913ccc-b455-4491-a4c1-aad7b3fc250b` completed with Celery SUCCESS and zero upstream requests. It atomically published `data-8f6c6d8256db0794b65e737aac9a490075d0d17152b05ab76a9af59e369e95f2` in 174.804 seconds: 111201 datasets, 823920 files and a 327170247-byte manifest whose SHA256 matches CURRENT and includes retained observations.
- Mac LaunchAgent run 191 downloaded 9003 files, verified the full 823920-file manifest, wrote zero stderr bytes and switched CURRENT with exit 0.
- Fund price 13, financial 18 and fund share 11 total 1080 jobs and 3102 unique references. The fixed-release verifier passed all manifest metadata and local SHA256 checks for 31204974 bytes with zero missing or corrupt references.
- The production image read seven relevant APIs with `--network none`, socket/DNS guards, empty tokens and a read-only mirror. Each returned three rows; upstream calls were zero.
- Cloud free disk is 222423474176 bytes, leaving 115049291776 bytes above the 100 GiB reserve. Main service, Tushare Worker and Beat are healthy.

Machine evidence: `docs/tushare-fixed-release-8f6-three-batches-20260911.evidence.json`. Complete history, revisions, known_at, PIT membership, RRG tradability and PCF remain open.
