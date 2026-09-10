# Tushare publish and document coordination candidate ready

- owner: mac candidate worktree
- branch: `codex/tushare-publish-document-coordination`
- baseline: `9f4b05f63ba49fb66d633fb0164b17a5070d4aee`
- status: candidate verified, production acceptance pending

## Finding

At 15:56:55 CST a due publish and a document task started together. The publish held the `documents.sqlite` write transaction for 25.910 seconds and later hit the 160-second soft limit in manifest serialization. The document task failed while committing a download result. The immediate publish retry overlapped another document task and caused a second lock failure while committing a parse result. No long audit reader overlapped either failure.

## Candidate

The Celery acquisition task passes a one-shot document-dispatch hook into `tick()`. A non-publication planning or acquisition path invokes it before doing its own work, preserving existing cross-worker parallelism. A due publication returns without invoking it, and the task dispatches one document job only after publication succeeds. A failed or killed publication therefore cannot start a new competing document job before its immediate retry.

No timeout, worker count, task budget, publication cadence, rate policy, data schema, retry state or fixed-release semantics changed.

## Verification

- Python 3.10.19 full Tushare suite: 955 passed, 5 skipped in 47.432 seconds.
- Document family: 72 passed; publish family: 20 passed.
- Focused worker/publication timing: 10 + 12 passed.
- Planning interval: 9 passed; tick timing: 5 passed; publication recovery: 12 passed.
- Ruff on changed files and `git diff --check` passed.
- Evidence: `docs/tushare-publish-document-coordination.evidence.json`.

Production acceptance must drain the two dedicated queues, align source/Git, restart only the acquisition and document workers, then observe one automatic due publish, its single post-success document dispatch, later normal parallel work, worker health and absence of new document lock failures. No Token or credential was read or recorded.
