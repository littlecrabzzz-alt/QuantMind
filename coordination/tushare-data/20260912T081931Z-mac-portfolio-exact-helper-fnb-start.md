# Tushare account-private portfolio exact helper start

- Owner: `/root/financial_next_batch`
- Base: `5f6a93032662985ae616e332aa22598bdcdaed78`
- Branch: `codex/tushare-portfolio-exact-helper`
- Worktree: `/private/tmp/quantmind-portfolio-exact-helper`
- Scope: new account-private `p_list` then derived `p_get` two-stage exact helper and direct tests only; no production, credentials, upstream, authority data or deployment.
- Privacy boundary: manifests and receipts containing portfolio names or holdings remain create-only inside authority with directory/file modes 0700/0600; Git and coordination retain only counts, hashes, state and non-sensitive task-set hashes.
