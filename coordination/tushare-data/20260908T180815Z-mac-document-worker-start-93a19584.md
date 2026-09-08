# Independent document consumer
- /root/structured_contracts, Mac isolated worktree quantmind-tushare-structured, codex/tushare-structured.
- Ownership: engine/tasks/tushare_tasks.py, qlib_app/celery_config.py, deploy/compose.cloud.yml, new scripts/test_tushare_document_worker.py. Parent/global agent own inline pipeline mode and publication optimizations.
- Snapshot tiny writer/active task change resumes explicit release in coordination/dual-node-development/20260908T165909Z-mac-auto-data-ready-*.md (matching shared record 165909, final sentence ownership released). Snapshot baseline copied from current master cd7efe4 into separate 90a711d; parent should cherry-pick only final implementation commit.
- Single separate tushare_documents queue consumer, 1536m/0.5 CPU; existing acquire task dispatches expires110 before tick, no new beat. Existing documents.lock, queue reuse and phase retries retained. Worker checks authority/ENABLED/config/free100GiB; no token read. Bounded default100 documents/90seconds, atomic status.
- Tests temp-only/mock broker, credentials and network forbidden; no deploy. Throughput improvement remains unmeasured and backlog ETA is not declared solved.
