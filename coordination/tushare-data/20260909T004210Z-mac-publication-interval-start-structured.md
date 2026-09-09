# Publication interval candidate start

Structured agent branch codex/tushare-publish-interval from100e4df. Own only tick small block in backend/shared/tushare_pipeline.py, new scripts/test_tushare_publish_interval.py and docs/tushare-publication-interval.md. Parent owns ledger/progress/concept; remaining DC candidate touches imports/discovery, not tick.

Retention prerequisite reviewed: API attempts committed per request, registration reads append-only attempt rowid, document download/parse attempts append transactionally, immutable original/extracted objects persist. Deferred publication coalesces mutable index/planning snapshots but retains promised raw/observations/attempts/text versions for next publish.

Config publish_interval_seconds defaults0. Enabled mode validates CURRENT before defer, checkpoints successful publish/noop in existing scheduler_state, clock rollback forces immediate publication check, failed publish cannot move checkpoint.900s is minimum interval, actual tick completion and independent15min Mac polling add delay. No production configuration or service changes.
