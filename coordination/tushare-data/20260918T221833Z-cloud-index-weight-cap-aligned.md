# Tushare index_weight cap fix cloud alignment

- Status: complete; Mac remains the only full-archive writer.
- Code: Mac and cloud project HEAD are `26fc8c33641887760bd171f035e4689ebc7250ec` on `master`.
- Handoff: Git metadata fast-forwarded while synchronized working files were retained. The combined handoff ended only on the inactive Mac sandbox API at `127.0.0.1:8000`; Tushare archive acquisition was unaffected.
- Cloud boundary: `tushare-research-cache.timer` is active and enabled; `ARCHIVE_RELOCATED.json` retains `source_paused=true`; no cloud `tushare_archive_worker` or `tushare_pipeline.py run` process was present.
- Mac runtime: LaunchAgent `com.quantmind.tushare-archive` remains running as the production full-archive writer.
