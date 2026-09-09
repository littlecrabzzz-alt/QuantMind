# Optional planning cadence

`planning_interval_seconds` defaults to `0`: initialization, planning and acquisition retain their previous per-tick behavior. A positive value requires a positive `publish_interval_seconds`; no production configuration is changed by this candidate.

With both intervals enabled, each tick holds the existing pipeline lock and opens the same durable database:

1. An overdue publication runs first and returns without changing the planning checkpoint.
2. Otherwise, first activation, a changed effective configuration, clock rollback, or an expired planning interval runs **initialize + plan_extended only**. It records a successful checkpoint after both return; no acquisition, source credentials, document processing or tail publication occurs in this mode.
3. Between planning rounds, initialization and planning are both skipped. Existing queued work, account/API gates, archive recovery, acquisition and document registration retain their existing behavior.

The checkpoint uses the existing scheduler_state table: one `planning_success:<configuration SHA-256>` row, replaced transactionally only on success. A failure keeps the previous checkpoint. Malformed checkpoints fail closed. Every effective config field is fingerprinted, so unrelated changes can cause an extra safe planning round; the hash does not replace any family's existing policy/signature. No family state, cursor, job identity, observation, raw body, attempt, gap or gate is reset or deleted. A later planning round uses the existing bounded planner and discovery membership refresh, including its unfinished snapshot rules.

The status adds `planning_cadence` (`interval_seconds`, `status`, `performed`, and when checked, `due`, `reason`, `config_fingerprint`, `last_success_at`, `next_due_at`). Top-level `planning_only` with zero requests is distinct from `publish_only` and acquisition. A publication-only tick reports planning as `not_checked`; its success must not be taken as a discovery refresh. Publication's current fixed release and pending/mirror fields remain independent.

A value such as 900 is a **minimum interval from the end of the last successful planning round**, not a promise of a refresh every 15 minutes. Tick cadence, an overdue publication, failures, and existing bounded/frozen history scans may delay the next discovery expansion further. It reduces repeated discovery work and makes planning and acquisition separate bounded tasks; it does not accelerate individual source responses or increase quota. New source membership and recent-job scheduling wait for the next planning round. Historical coverage obligations and durable observations remain; transient source data availability is not guaranteed by the planner and this setting is not a stronger real-time sampling guarantee. The already large pending queue continues to be consumed. Mac's independent publication mirror can add further delay.

Do not enable this candidate solely on a synthetic benchmark. Review production status over planning-only, acquire-only and publication-only cycles; check new source arrivals are picked up in later rounds and monitor queue fairness and memory. The setting is not an acquisition budget or memory-limit increase. Direct `Pipeline.initialize`, `plan_extended` and `publish` calls remain immediate.

Offline regression (Python 3.10):

```bash
PYTHONPATH=scripts /tmp/quantmind-calendar-factor-test310/bin/python -m unittest test_tushare_planning_interval test_tushare_publish_interval test_tushare_tick_timing test_tushare_planning_progress test_tushare_extended_pipeline -q
```

Tests use temporary SQLite databases and deny network. They cover default compatibility; first activation; restart/defer; configuration A→B→A; publication priority; clock rollback; initialization/planning/checkpoint failure and rollback; malformed configuration/checkpoints; old job/cursor preservation; and actual existing planner discovery expansion after a deferred source arrival.
