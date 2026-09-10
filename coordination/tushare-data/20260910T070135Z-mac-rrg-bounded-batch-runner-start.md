# RRG exact bounded batch runner: start

- UTC: `2026-09-10T07:01:35Z`
- Owner: `/root/rrg_data_closure_next`
- Base: `origin/master` at `bec7e6aa9fcf6c94ba443dc9976478268c3dccee`
- Branch: `codex/rrg-bounded-batch-runner`
- Scope: audit the imported 1,767-job RRG acquisition batch and implement a default plan-only, hash-pinned runner whose upstream selections are limited to the verified manifest task IDs.
- Safety: Mac worktree only; no production root, token, upstream request, publication, release switch, queue deletion, or task identity mutation.
- Required reuse: Pipeline normalization, account/API reservations, local daily quota, shared lock, attempts/retries, pagination and split state transitions.
- Bounds: execute path must reject more than 360 upstream requests or 90 seconds and remain interruptible.
