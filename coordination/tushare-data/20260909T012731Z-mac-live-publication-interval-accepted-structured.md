# Real publication interval cycle accepted

Structured agent, helper-only read-only acceptance. Production activation/restart was parent-owned. No runtime edits, provider requests, remote writes, clock adjustment, manual publish or worker control by this task.

Baseline automatic publish01:09:52Z data-e9da1c41f9c3b8e6846db9dc3d778092f9001f52a7c764b5d5f29afb563057a4; next successful automatic publish01:25:39Z data-6a46d2c09cc5038ad359a7f18919abbe2d0ca26d7519e2b057b7e43d5ae9780b; actual947s. Five positive-request deferred samples captured; no manual clock/publish used to satisfy900s.

Baseline publication cutoffs55186 API/4432doc were derived from unique observations in fixed manifest and docattempt tail shard. At capture DB already55367/4444; those concurrent additions were retained as delta, not falsely classified published. Final cutoff57676/4605 gives2490 API events and173 document events.6438 distinct files/261619850bytes SHA checked and all metadata references matched new manifest:2490objects+2490observations+1325Parquet+73attachments+60extracted. Missing0.

Additional document timeline verification read only1 affected attempt shard, comparing all173 ids/document_id/phase/created_at/canonical full-resultSHA and references to source rows and prior capture; missing/different0. API event count denotes checked source DB rows; response/observation/Parquet closure is proven, not a new API-attempt metadata format. Mac transfer was not checked by this helper. Not global-history/PIT/strategy/sustained-throughput acceptance.

Deferred normal batches total104.27–105.81s, publish checks0.98–1.08s. Due batch336requests,total130.27s,publish26.69s. Report /tmp/tushare-live-interval-acceptance/report.json; full state.json beside it; helper /tmp/verify_tushare_live_interval.py and offline fixture test /tmp/test_verify_tushare_live_interval.py. Helper bounded each poll to500API/200docrows,25shash/256MiB.

Evidence digests at handoff:

/tmp/tushare-live-interval-acceptance/report.json SHA256 3f7f64666f4bbc817b5c48425d8bed681f063002383d35b52b1ec656f811981f

/tmp/verify_tushare_live_interval.py SHA256 dad6d2b8b5b6ed1b7294dfeee45c7e1a444eb4785c0ddd4fe2b2d64d967a255b

/tmp/tushare-live-interval-acceptance/state.json SHA256 1d73ef42ed5e357ae85d2bad07c05b32318c4ecf4b293b9a0d320d2a74e7c34b
