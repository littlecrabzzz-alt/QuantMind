# Tushare RRG acquisition shard importer

`scripts/import_tushare_rrg_acquisition_shard.py` is the authority-side bridge from an inert RRG acquisition batch to the existing Tushare pipeline queue. Its default mode is read-only `plan_only`; it validates the complete batch and reports what one optional shard would enqueue.

An execution must name one shard, pin both the batch-manifest SHA-256 and shard SHA-256, and set an explicit upper bound. Before writing, the importer:

1. verifies the audit report, adjacent audit manifest and collection-plan hash chain;
2. verifies every listed shard's path, size, SHA-256, row count and batch totals, and rejects extra shard files;
3. rebuilds every task through the current `Pipeline.enqueue` contract and compares `task_id`, `logical_key`, `job`, `group_name`, `priority` and `epoch`;
4. requires the configured cloud authority root, the existing schema at version 6, and an exclusive nonblocking `pipeline.lock`;
5. imports at most one bounded shard in one SQLite transaction and verifies the stored identity before commit.

Re-entry is idempotent because the existing pipeline task identity is deterministic. Existing rows must still match the prepared identity exactly. The receipt contains only pinned hashes, counts and queue states; it omits parameters, credentials and authority paths.

The importer never reads the Tushare Token, calls the network, runs a worker, publishes a release or switches `CURRENT`. A successful import only creates pending pipeline jobs. Empty upstream responses later remain terminal request evidence under the existing pipeline contract; they do not establish that dividends never existed, infer suspension, fill a missing price or establish point-in-time membership.

Plan-only example:

```bash
python -B scripts/import_tushare_rrg_acquisition_shard.py \
  --batch-manifest /path/to/batch/batch-manifest.json \
  --manifest-sha256 MANIFEST_SHA256 \
  --audit-report /path/to/audit/report.json \
  --shard shards/0001-fund_div.jsonl
```

Authority execution is deliberately a separate, explicit operation:

```bash
python -B scripts/import_tushare_rrg_acquisition_shard.py \
  --batch-manifest /path/to/batch/batch-manifest.json \
  --manifest-sha256 MANIFEST_SHA256 \
  --audit-report /path/to/audit/report.json \
  --shard shards/0001-fund_div.jsonl \
  --expected-shard-sha256 SHARD_SHA256 \
  --max-jobs 250 \
  --execute
```

Run the execution command only inside the verified cloud authority container with the batch and its source audit mounted read-only. The configured pipeline root is selected by the application; `--root` is available for controlled verification and must resolve to that exact configured root.
