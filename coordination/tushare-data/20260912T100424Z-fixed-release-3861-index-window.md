# Tushare fixed release 3861 index window closure

- Normal scheduler task `400ce5d2-a1f6-43f4-9388-30efe9b13926` completed `publish_only` with Celery SUCCESS in 378.887 seconds, made zero supplier requests, and atomically published `data-3861558a914f5066de24a7c315442a1ba079269139f7309765f4a377704bbe9c`.
- The 395,562,427-byte manifest self-hash matches its release ID and contains 902,390 files and 125,323 datasets.
- Cloud and Mac independently verified all 1,075 references / 17,227,996 bytes for `index_daily` batch 18 and all 1,041 references / 11,653,430 bytes for `index_weight` batch 14. Missing, metadata and physical SHA errors were all zero.
- Mac LaunchAgent run 246 downloaded 6,316 files, verified the full release and atomically switched CURRENT. The normal Tushare worker and Beat were restored healthy with restart count zero and no OOM.
- Full recovery snapshot `snapshot-20260911T230002081103Z` continues its Mac pull independently; the old snapshot pointer remains published until complete verification.
- Next gate: implement and test a dedicated `index_weight` sibling-pair descendant contract before executing split obligations. A fresh drained authority lock is required for the next `index_daily` candidate.
