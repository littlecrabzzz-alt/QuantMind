# Bounded, resumable document registration

Candidate based on `0c18fb2`; no production deployment or upstream requests.

## Failure and scope

The reported production task `8c6a1bc0-9b58-4387-ba85-3ff02cde72fb`
reached the 160-second soft limit in `tick -> register_documents ->
enqueue_documents` at the document SQLite context. That trace does not establish
whether BEGIN, a statement, or COMMIT was waiting. The old code had no registration
time budget: up to 20 observations, each with arbitrarily many source rows, each
opening a document connection with a ten-second busy timeout and committing the
whole observation. It also repeatedly filtered an unbounded unrelated attempt tail.
The prior deferred identifier split does not bound this separate stage.

The candidate changes only document registration and its DB connection options.
It does not change request budgets, quotas, worker resource/time limits, publication,
download/parse claims, source objects, observation identities, or authoritative
SQLite schemas. Direct `enqueue_documents` calls without a deadline retain their
existing count-only return and transaction behavior.

## Bounds and recovery

`Pipeline.register_documents(max_observations=20, *, max_records=500,
max_seconds=5)` scans at most 1,000 consecutive attempts and processes at most 500
source records by default. Each document transaction contains at most 100 records.
Its monotonic deadline covers the whole invocation; SQLite gets a 50 ms maximum
busy wait and a deadline progress handler, including old document-schema setup.
The pipeline connection's prior busy timeout is restored afterwards.

A completed observation still advances the existing `document_cursor`. An
unfinished observation uses one `scheduler_state` key:
`document_offset:<attempt rowid>:<SHA256(result + attachment fields)>`, with the
number of fully committed source rows as its value. Old databases need no migration.
Missing or changed partial source identity fails closed; offsets are never silently
applied to another response. The whole raw response and every attachment field
retain the existing reference hash and reuse semantics.

The crash order is deliberate:

1. Register all attachment fields for the bounded rows in one document transaction.
2. Commit that document transaction.
3. In a separate pipeline transaction, save the row offset, or advance the complete
   observation cursor and remove the offset.

A failure before step 2 rolls back the chunk and reports zero committed progress.
A failure between steps 2 and 3 leaves the old checkpoint: replay uses the same
reference IDs and does not duplicate or miss attachments. A completed step 3 only
skips rows already committed in the document DB. Unexpected failures propagate;
SQLite busy/interrupted returns `deferred_database_busy` / `deferred_budget` and
preserves resumability. A checkpoint failure additionally reports
`checkpoint_pending`; `processed_records` can include already committed rows that
will be harmlessly replayed. `observations` counts only fully checkpointed responses.

Empty source responses retain `no_records`; an expired budget is never mistaken
for an empty response. Unrelated attempts advance the scanned cursor without
changing their raw/observation/attempt rows. New future attachment contracts may
require an explicit historical registration backfill, as with the existing cursor
model; this change does not claim that future schemas are already registered.

## Boundaries

The deadline is cooperative, not an OS-level hard execution limit. One existing raw
JSON read/decode and one record's Python hashing are still indivisible operations;
filesystem stalls and COMMIT fsync are not preempted. Source rows are not replaced
by projected Parquet rows because that could change request-aware reference
identity. SQL execution is interruptible and lock waits are bounded. Large responses
resume over later ticks, potentially postponing attachment availability; their raw
responses and uncompleted registration obligation remain durable. No production
speedup or complete resolution of every possible 160-second timeout is claimed.

## Verification

Python 3.10, temporary SQLite/objects only, socket/DNS/secret access denied:

```sh
PYTHONPATH=scripts /tmp/quantmind-calendar-factor-test310/bin/python -m unittest discover -s scripts -p 'test_tushare_document*.py' -q
PYTHONPATH=scripts /tmp/quantmind-calendar-factor-test310/bin/python -m unittest discover -s scripts -p 'test_tushare_*pipeline.py' -q
PYTHONPATH=scripts /tmp/quantmind-calendar-factor-test310/bin/python -m unittest test_tushare_archive test_tushare_tick_timing test_tushare_publish_timing test_tushare_publish_interval test_tushare_planning_interval -q
```

62 + 173 + 43 tests passed. Eleven dedicated tests cover 1,205 rows over three
reopens against the exact baseline enqueue implementation, both document BEGIN
and COMMIT lock contention, a busy pipeline checkpoint after document commit,
crash/replay, SQL deadline interruption, source mutation/deletion, bounded unrelated
attempt scanning, empty responses and cross-observation reuse. The baseline parity
test needs Git object `0c18fb2` available locally. Two existing fixtures were updated
for additive registration report fields and the real committed-progress receipt.
