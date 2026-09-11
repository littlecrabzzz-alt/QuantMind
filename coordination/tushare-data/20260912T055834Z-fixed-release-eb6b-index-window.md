# Fixed release eb6b closes the six-batch index window

- The normal `publish_only` task `88fab916-342e-45d1-9fa6-1f9a686cd06a` succeeded at 05:52:19 CST in 231.392 seconds and atomically published `data-eb6bf9a06e48821b8dccf7765846c2f87593aa3560c60ebbdef57a0529d9e1bd`.
- The release manifest is 386,421,386 bytes and contains 121,328 datasets and 883,963 files. The old 76b release excludes all 6,267 exact references; the new eb6b release contains and physically verifies all 6,267 references and 91,464,651 bytes.
- Mac LaunchAgent run 232 automatically downloaded 8,183 files, verified all 883,963 release files and switched local CURRENT at 05:58:34 CST. A second exact-reference verifier passed with no missing, metadata or physical errors.
- With token variables empty and socket/DNS access blocked, local fixed-release reads returned three rows each for `index_daily` (17 columns) and `index_weight` (11 columns), with zero upstream calls.
- The ordinary worker and Beat were restored with their existing containers. Both are healthy; worker restart count is zero and OOMKilled is false.
- Full pins and validation hashes are recorded in `docs/tushare-fixed-release-eb6b-index-window-20260912.evidence.json`.
