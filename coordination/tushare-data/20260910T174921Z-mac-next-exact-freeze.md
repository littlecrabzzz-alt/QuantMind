# Tushare next exact freeze

- Mac master `10e6c526`; cloud authority worker and Beat intentionally stopped after canceling the acquisition consumer and naturally draining the active task.
- Fixed release `data-469f77386a446840774a5d78b7384d0bedcc4c6b1f89035b3512b52fe09703c1` is published and mirrored to Mac; 679991 files verified and offline reader probes used zero upstream calls.
- Financial batch 10 preparation failed closed before manifest creation: the bounded recent candidate window contained only cross-epoch terminal logical duplicates. Increase the bounded per-market candidate scan from 10x to 100x, test, commit, deploy, and retry from the stopped authority.
- Continue with index_weight batch 2 if the financial batch still cannot be frozen. Execute only immutable exact manifests and receipts, then restore the dedicated worker and Beat. Do not touch unrelated RRG or research worktree files.
