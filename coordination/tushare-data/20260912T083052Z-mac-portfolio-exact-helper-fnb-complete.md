# Tushare account-private portfolio exact helper candidate complete

- Owner: `/root/financial_next_batch`
- Base: `5f6a93032662985ae616e332aa22598bdcdaed78`
- Branch: `codex/tushare-portfolio-exact-helper`
- Commit: `e3b35cf2bf1ebff3a08fb63b0db3b625cf2cfe06`
- Worktree: `/private/tmp/quantmind-portfolio-exact-helper`
- Code-set SHA-256: `c54924f768120829d312092356c219349e1edcc4e585803972e9ecd2c3c7c785`
- Production effects: none; no credentials, upstream, authority data, service or deployment access.

Candidate behavior:

- One helper exposes explicit prepare, default offline plan-only, and explicit execute modes for a one-request list stage followed by a zero-to-thirty-request member stage.
- Execution pins CURRENT release/manifest, authority config, code set, enable marker and task/request inventories; uses the existing authority check, nonblocking pipeline lock, exact task scope, 100 GiB reserve and 90-second hard deadline.
- Token is obtained before any enqueue. Both stages use a local 30 rpm API ceiling; lower configured/account gates remain effective.
- Member requests derive only from the same-authority, same-snapshot-epoch list task with exactly one successful attempt and verified observation/object hashes. Same-epoch prior execution evidence fails closed; the same request in another epoch remains allowed.
- All manifests and receipts are create-only under the authority `private-portfolio-batches` directory with directory/file modes 0700/0600 and atomic publication. Standard output and receipts contain counts, states and hashes only.
- The helper never calls portfolio mutation APIs, publishes a release, or changes CURRENT.

Validation:

- New helper suite: 8 passed.
- Focused helper/contracts/exact-runner/HTTP/QuantBot group: 40 passed.
- Full Tushare discovery before the final isolated atomic-write hardening: 1176 run, only the two pre-existing `fina_mainbz_vip` fixture failures, 5 skipped. The final hardening was followed by the 40-test focused rerun.
- Ruff check/format, Python compile and `git diff --check`: passed.
