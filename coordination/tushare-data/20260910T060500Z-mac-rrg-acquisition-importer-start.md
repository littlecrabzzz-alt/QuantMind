# RRG acquisition shard importer start

- Node: Mac isolated worktree
- Branch: `codex/rrg-acquisition-importer`
- Baseline: `4a1aafab33b897605aabf2c826fba83909727718`
- Scope: plan-only by default; authority-only, lock-held, schema-6, single-transaction bounded import of one verified prepared shard via existing Pipeline.enqueue.
- Verification chain: explicit batch manifest SHA, pinned audit report and collection-plan hashes, every shard hash/inventory, and recomputed task/job identity.
- Boundaries: no Token, network, upstream request, worker run, publication, CURRENT switch, price fill, suspension inference or PIT inference.
