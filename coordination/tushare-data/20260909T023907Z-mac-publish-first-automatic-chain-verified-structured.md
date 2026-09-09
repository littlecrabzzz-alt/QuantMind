# Automatic publish-first worker chain verified (read-only)

Structured agent, complete and no runtime ownership. Used existing cloud-compose quantmind business entry to GET exact Celery backend task metadata; bounded tushare-worker logs since02:25:00Z, tail250 then2500. Safe compact result fields only; no provider calls, task dispatch, scheduler/config writes, manual publish, mirror, restart, or secret output.

Specified task2f6e3ceb-5752-486e-aa26-5003c96f2d27 was SUCCESS at02:24:33Z, **acquire_only**145requests /121.762303s with cc8 release; it is not the automatic publication proof.

Actual automatic task **e7b0e64f-16ee-400b-b807-17ebcbfbd0af**, engine.tasks.tushare_acquire on celery@bb73f18d769b: received02:28:29.201Z; SUCCESS02:29:18.457846Z. Backend status=publish_only, requests=0, publication.mode=publish_only/status=published/performed=true/pending=false; failed_stage=null. New release **data-2e1585a2c28036ec7f0474a591d1424e863c17f81d3543135182d5317c2804aa**; last_success1788920958, next_due1788921858, interval900. Total pipeline49.244980s; worker log49.260050s; outer publish47.438213s; inner measured publish43.218693s. Main measured pieces retain_previous17.705633s, coverage_and_closure12.673010s, scan_attempts_and_stat4.254608s, document_index1.135111s; publication_check1.713656s. This is real dedicated-worker execution, not quantmind's earlier manual14.6s publication.

Immediate successful acquisition recovery, same worker/new release/checkpoint:
- c65a2a9d-864f-43d0-8ddf-9b87d7b08feb, received02:29:29.545Z → SUCCESS02:31:26.285273Z, acquire_only186requests,116.650651s total.
- 12f5c7ad-67ee-4c6d-80b6-82e66d17e050, SUCCESS02:33:31.192589Z, acquire_only217requests,121.664481s total.
- Both publication.performed=false/status=deferred/pending=true, failed_stage=null. Later02:35:28Z completed status also shows166requests/117.619683s; CURRENT matches2e1585. Pending acquired data is not labelled mirrored; mirror_status remains not_checked.

Final report `/tmp/tushare-publish-first-acceptance-report.json` SHA `9a9bbd0e4e8a6241d8fcc80d80c60223aa3306f4160de4cfd04ff9525b286ed9` contains exact timings and source/report/helper SHA mapping. Raw-safe compact inputs: `/tmp/tushare-publish-first-automatic-evidence.json` (specified task+current state), `/tmp/tushare-publish-first-compact-logs.json` (only received/succeeded IDs/times/modes), `/tmp/tushare-publish-first-chain-evidence.json` (actual publish and two post-publication exact backend records). Helpers `/tmp/verify_tushare_publish_first_task.py`, `/tmp/read_tushare_publish_first_logs.py`, `/tmp/verify_tushare_publish_first_chain.py`; final helper reuses first helper's CODE literal to keep safe-field projection identical. No broad backend scan or full filesystem scan.

This proves one observed automatic publish-only success and subsequent acquisition continuation, not sustained speedup, all historical completeness, or Mac verification of2e1585. No repository existing files modified; parent owns progress/docs and next performance work.
