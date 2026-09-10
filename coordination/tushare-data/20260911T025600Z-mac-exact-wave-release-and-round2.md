# Tushare exact wave release and fund_nav round 2

- owner: mac
- git: `54ae40bd3277538f0e59cd392211b4d00c3ef37f`
- cloud authority: `/root/data/disk/quantmind/project/data/tushare`
- fixed release: `data-dbd1efcca51b442c2a72cbacc28dd4d61883c0a232eebecc410d48bdf02d7ec9`
- release files: 692727
- exact tasks closed into manifest: 1440/1440
- Mac mirror: verified, 12735 downloaded, 692727 checked, exit 0
- offline readback: Mac socket/DNS blocked and token absent; cloud `--network none` and empty token; four target APIs returned local rows with zero upstream calls
- deployment: `tushare-worker`, `celery-beat`, and dependencies healthy; restart 0, OOM false; first post-deploy acquisition succeeded in 145.746 seconds
- fund_nav empty review: round 2 code deployed, but production calls remain zero until round 1 becomes due at or after `2026-09-11T12:26:34.077603Z`
- retained boundaries: `history_complete=false`, historical revisions incomplete, PIT false, RRG `blocked_data`
- nonblocking gap: generic CLI `codes` uses `ts_code` for `index_weight`; date-filtered offline reads work, code-filter selector needs a separate fix
- machine evidence: `docs/tushare-exact-wave-release-20260911.evidence.json`
