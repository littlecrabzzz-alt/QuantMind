# Tushare RRG descendant exact runner

The original RRG manifest contains 49 `etf_limit` parent task IDs. One completed directly; 48 saturated and created durable descendants. The existing exact runner installs only the original manifest IDs in its connection-local scope, and `Pipeline.next_job()` selects only `pending` rows. The 48 parents are `split_pending`, while their child IDs are absent from that scope, so another invocation of the parent runner cannot select them.

`scripts/run_tushare_rrg_descendant_batch.py` derives the complete current descendant graph from those hash-verified parents. Its default plan mode opens schema 6 read-only, verifies every source-parent identity, rejects missing, cyclic, non-`etf_limit` or out-of-group descendants, and reports every task ID with depth, state, priority, `tries` and attempt-row count. It does not read credentials, call the network, publish a release or change `CURRENT`.

Execute mode re-derives the graph under the exclusive nonblocking `pipeline.lock`. Before reading the Token it requires exact SHA-256 values for the authority description, current config, deployed helper and complete descendant task set; verifies the configured authority mount, regular `ENABLED` marker and schema 6; and checks at least 100 GiB free. A changed or newly expanded descendant graph changes the task-set hash and fails closed. It then gives only the pinned descendant IDs to the existing exact Pipeline scope, which selects their currently `pending` rows and reuses the existing normalization, checkpoint, split/reconciliation, account/API rate gates and daily quotas. One invocation is capped at 360 upstream calls and 90 seconds. Children created during that invocation are durable but remain outside its pinned scope until a fresh plan.

Run plan-only in the authority container and save its stdout for review:

```bash
sudo -n bash scripts/dual-node.sh cloud-compose exec -T quantmind \
  python -B /app/scripts/run_tushare_rrg_descendant_batch.py \
  --batch-manifest /data/tushare/validation/rrg-acquisition-import-20260910T0618Z/batch/batch-manifest.json \
  --manifest-sha256 3ceaa518a73af92df4c824a9fa2c4fc7a65343a75569396643b749b091927d81 \
  --audit-report /data/tushare/validation/rrg-acquisition-import-20260910T0618Z/audit/report.json \
  --root /data/tushare
```

Use all four hashes from that exact reviewed plan in one bounded execution. Re-run the plan if any hash or descendant count has changed:

```bash
sudo -n bash scripts/dual-node.sh cloud-compose exec -T quantmind \
  python -B /app/scripts/run_tushare_rrg_descendant_batch.py \
  --batch-manifest /data/tushare/validation/rrg-acquisition-import-20260910T0618Z/batch/batch-manifest.json \
  --manifest-sha256 3ceaa518a73af92df4c824a9fa2c4fc7a65343a75569396643b749b091927d81 \
  --audit-report /data/tushare/validation/rrg-acquisition-import-20260910T0618Z/audit/report.json \
  --root /data/tushare \
  --expected-authority-sha256 REVIEWED_AUTHORITY_SHA256 \
  --expected-config-sha256 REVIEWED_CONFIG_SHA256 \
  --expected-helper-sha256 REVIEWED_HELPER_SHA256 \
  --expected-task-set-sha256 REVIEWED_TASK_SET_SHA256 \
  --max-requests 360 --max-seconds 90 --execute
```

Completion of these price-bound partitions cannot classify ETF suspensions or opening-auction tradability. It also does not supply historical member `known_at`, versioned ETF-industry mapping, historical-universe proof, exact-day PCF availability/revisions or portfolio weights. RRG therefore remains `blocked_data` until those independent PIT inputs are verified.
