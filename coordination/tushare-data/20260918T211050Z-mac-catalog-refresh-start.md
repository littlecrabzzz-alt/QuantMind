# Tushare official catalogue refresh start

- Owner: Mac local archive task
- Scope: refresh the public official catalogue, register seven newly listed leaf APIs, keep full acquisition on Mac, and preserve cloud as research cache only.
- Baseline: `master` at `356d8d48153203dc9d68dcfd284d00af68bb94b9`.
- Public evidence: the 2026-09-19 sidebar contains 270 entries versus the saved 263; new doc IDs are 383, 493, 494, 495, 496, 497, 498.
- Safety: no token is stored in Git; development uses an isolated worktree; the production writer remains running during code and public-document review.
- Next: add reviewed contracts and deterministic planning, update catalog/ledger evidence, run isolated tests, then deploy and perform bounded real permission/throughput verification.
