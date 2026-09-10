# Defer expensive identifier fanout after durable capture

This candidate separates a full identifier-discovery fanout from acquisition. It
changes no configuration, quota, request count/time budget, worker resource limit,
cache setting, family policy, planning cursor or source coverage scope.

## Evidence and remaining uncertainty

The planning-cadence acceptance records an acquire-only soft timeout after157.201s
in acquire, with initialization/planning absent. Successful acquire-only rounds
also exist (44/95requests; total121.63/106.16s). Supplied failure slot1 in
`/tmp/planning-cadence-live-samples.json` has a Celery FAILURE but null detailed
stage fields and no method traceback. Its SHA is
`18a1eb9d728842808bcf76b2fcf7a6a9c401840beddc79036b1ed9f9a67655db`.
**The exact production trigger remains unconfirmed.**

There is a concrete unbudgeted stacking path in baseline4446d36: `run` checks its
90s loop condition before a request, then a saturated cross-section calls
`split_request` synchronously. Its identifier fallback runs the complete
`identifiers()` discovery, measured around71s in the real planning acceptance.
A request finishing near the budget end can therefore add an entire discovery
scan before normalization and attempt checkpointing. The raw object and
observation already exist, but a soft interrupt before the attempt commit can
cause a later retry to repeat the parent HTTP request.

An isolated real capture/SQLite/Parquet reproduction uses a simulated clock:
response completes at89s and full discovery consumes71s. Exact baseline `run`
compiled from4446d36 takes160s; this candidate records the capture at89s and
resumes its local fanout in a separate71s run. Both produce the same three child
codes (discovered + parent-observed), exactly one MockTransport request and an
`universe_unverified` gap. This is a mechanism reproduction, not a production
throughput measurement. Report `/tmp/tushare-acquire-deferred-split-report.json`,
SHA `95ace309e75bebf4f26e07303de8abd6d9e9f9b918fab63ad97645c6aa662dd2`;
re-run with `/tmp/quantmind-calendar-factor-test310/bin/python
/tmp/tushare-acquire-deferred-split-reproduce.py` from this isolated worktree.

## Durable behavior

For a saturated parent that requires full identifier fallback, acquisition adds
`partition_deferred={version:1,kind:identifier_fanout}` to the local result and
sets its existing job state to `split_pending`. It performs the existing
normalization and commits raw/observation/Parquet references plus the capture
attempt before returning to another acquisition iteration. No upstream response
bytes or observation fields are modified by the scheduling marker.

The next `run` checks the existing indexed `split_pending` state for a marker.
If its deadline has expired it leaves the task untouched. Otherwise it processes
**at most one** marked parent through the existing `split_request`, reconciles
that parent, commits, and returns with zero requests. It does not reserve an
account/API gate, consume a family opportunity, retrieve credentials or issue
HTTP for this work. `partition_work` reports the existing job ID and outcome.
The tick still performs its existing surrounding archive/document registration
steps; this change does not introduce another scheduler or service.

Successful resume updates the job's derived split result only. It does not
rewrite the original attempt, source observation, epoch, logical key, retry
counter, priority or request. The exact existing discovery path, observed-parent
union, child identity, repeated-entry handling and closure logic are reused;
unknown universe remains a gap. A transaction failure rolls back newly inserted
children and leaves the durable marker for local retry. If normalization failed,
the fanout obligation still runs: the old synchronous path already created these
children before normalization. After deferred creation the parent returns to
`blocked` with its normalization error, and closure remains unverified.

Date bisection, observed futures partitions and documented pagination keep their
existing synchronous paths. Direct `Pipeline.split_request` calls also remain
immediate. No schema migration is required; old unresolved rows without a marker
retain their existing handling. Unsupported markers/contracts fail closed with
evidence intact. A pending parent's raw/observation/Parquet are publishable before
its deferred local work completes; publication does not imply partition closure.

`run` also checks its existing deadline after expansion and selection, preventing
an expensive local selection from dispatching another HTTP request after the
budget has expired. A rate opportunity already conservatively reserved during
selection is not undone; there is no attempt or invented HTTP result for it.

## Limits and verification

This does not cap the duration of an individual discovery scan or an individual
HTTP response. It does not prove production RSS headroom under1GiB. Cache remains
hold. If a single fanout grows beyond the task limit, it remains durable but may
need further work. HTTP per-operation timeouts, slow normalization, reconciliation,
queue fallback scans and final status/document registration can still add time;
none is claimed to be solved here. Many saturated parents can require several
zero-HTTP local-work rounds before acquisition resumes. This tradeoff preserves
requested work instead of retrying expensive capture after an interrupted batch.

Python3.10:83 focused tests passed in1.109s (9 new deferred tests plus observed
fanout, futures, closure, rate and cadence regressions); all173 `*_pipeline.py`
tests passed in13.128s. Four prior synchronous-fanout fixtures now explicitly run
the separate resume step; their original field/child/count/closure assertions
remain. Tests deny sockets/DNS/secret retrieval, use temporary SQLite and
MockTransport, verify artifact SHA, restart/rollback/deadline/idempotence,
normalization-error obligations, pending publication, old rows and unchanged
request gates/family cursor. `EXPLAIN QUERY PLAN` selects `jobs_pending(state=?)`
for the new parent lookup; it does not scan millions of pending HTTP jobs.

```bash
PYTHONPATH=scripts /tmp/quantmind-calendar-factor-test310/bin/python -m unittest test_tushare_deferred_split test_tushare_observed_fanout test_tushare_futures_observed_split test_tushare_extended_pipeline test_tushare_partition_closure test_tushare_publish_interval test_tushare_planning_interval test_tushare_rate_policy -q
PYTHONPATH=scripts /tmp/quantmind-calendar-factor-test310/bin/python -m unittest discover -s scripts -p 'test_tushare_*pipeline.py' -q
```
