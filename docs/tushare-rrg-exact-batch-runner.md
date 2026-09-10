# Tushare RRG exact bounded batch runner

The imported RRG acquisition batch is valid but the ordinary worker is not an exact-batch executor. The 2026-09-10 authority snapshot found all 1,767 tasks, with `fund_div` at 4 `empty` and 1,714 `pending`, and `etf_limit` at 6 `split_pending` and 43 `pending`. Of these, 1,765 were priority 24. A production observation reported that they still had not been selected because priority only orders tasks after normal family/API scheduling chooses their queue.

Calling the ordinary `Pipeline.run()` cannot safely solve that delay for a named batch. It performs global planning expansion, may resume an unrelated deferred identifier split, may reconcile unrelated partitions, and selects from the complete queue. Raising priority therefore does not prove that the next 360 calls belong to the pinned 1,767 task IDs.

`scripts/run_tushare_rrg_acquisition_batch.py` adds a separate, default `plan_only` entry point. It verifies the complete importer hash chain and reports the exact task inventory without opening authority state, reading a credential, or calling the network. Its execute mode installs the verified task IDs in a connection-local SQLite temporary table. `Pipeline.run(..., task_ids=...)` then:

- selects only pending tasks in that temporary set;
- round-robins the APIs in the set, so the 43 remaining `etf_limit` parents receive opportunities alongside the much larger `fund_div` population;
- preserves priority and row order inside each API;
- uses the existing account and API reservations, observed cooldowns, local daily quota, response capture, normalization, attempts, retries, pagination, split creation and child reconciliation;
- skips global expansion, global deferred-split resume and global initial reconciliation for this invocation;
- never selects children created by pagination or splitting unless their IDs were already in the pinned input set.

Existing `split_pending`, `empty`, completed or blocked jobs are reported but are not requested again. A new saturated response may create the same durable split children as the ordinary Pipeline; those children remain outside this invocation. An upstream permission denial retains the Pipeline's account-wide capability evidence and same-API/source pending-job block, because narrowing that safety response could cause a later ordinary worker to retry a known unauthorized interface.

Execution requires every one of these gates before the Token is read:

1. the configured cloud authority mount and regular `ENABLED` marker;
2. an exclusive nonblocking `pipeline.lock` and an existing schema 6 database;
3. the full source/audit/batch/shard hash chain;
4. the pinned all-task-ID hash and exact stored `task_id`, `logical_key`, `job`, `group_name` and `epoch` for all 1,767 rows;
5. the pinned authority config hash and exact helper-file SHA-256;
6. at least 100 GiB free space, the same reserve used by the ordinary tick;
7. explicit bounds no greater than 360 upstream calls and 90 seconds.

The 90-second bound is both checked by `Pipeline.run` and backed by a process alarm on supported main-thread Unix execution. SIGINT/SIGTERM can also stop the command; prior responses remain durably checkpointed one at a time and the OS releases the shared lock. A successful receipt contains hashes, state/API counts and attempt deltas, without task parameters, paths, credentials, response bodies or Token material. The command does not publish or switch `CURRENT`, and verifies that `CURRENT` and the pinned config did not change while it held the lock.

Plan-only example:

```bash
python -B scripts/run_tushare_rrg_acquisition_batch.py \
  --batch-manifest /read-only/rrg-batch/batch-manifest.json \
  --manifest-sha256 3ceaa518a73af92df4c824a9fa2c4fc7a65343a75569396643b749b091927d81 \
  --audit-report /read-only/rrg-audit/report.json
```

Review the plan output, calculate the deployed helper and current authority config hashes, then invoke one explicit bounded execution inside the verified authority container:

```bash
python -B scripts/run_tushare_rrg_acquisition_batch.py \
  --batch-manifest /read-only/rrg-batch/batch-manifest.json \
  --manifest-sha256 3ceaa518a73af92df4c824a9fa2c4fc7a65343a75569396643b749b091927d81 \
  --audit-report /read-only/rrg-audit/report.json \
  --expected-task-ids-sha256 62caad354d15bdf27022392a5dbc80b33e0a54f9f1c1038a26b0ad85477fb283 \
  --expected-config-sha256 CURRENT_AUTHORITY_CONFIG_SHA256 \
  --expected-helper-sha256 cf5bffec76246cb414a4df18a80d8353af061613da0584af4d616bae05f98a4d \
  --max-requests 360 \
  --max-seconds 90 \
  --execute
```

This runner closes acquisition evidence for `fund_div`, `etf_limit`, and an explicitly prepared `fund_daily` diagnostics-only batch; it does not itself publish a fixed release or make RRG research-ready. A zero-row diagnostic stays unclassified and is never filled or relabelled as a suspension. Historical member `known_at`, versioned ETF-industry mapping, authoritative tradability, and exact daily PCF remain separate `blocked_data` gates.
