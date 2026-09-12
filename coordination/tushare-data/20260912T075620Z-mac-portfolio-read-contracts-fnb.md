# Tushare portfolio read contracts candidate

- Owner: `/root/financial_next_batch`
- Base: `21c49a2d8421`
- Branch: `codex/tushare-portfolio-read-contracts`
- Worktree: `/private/tmp/quantmind-portfolio-read-contracts`
- Scope: the minimal default-disabled read-only `p_list` and `p_get` contract, planning, registry, query integration, and direct tests.
- Exclusions: `p_save`, `p_delete`, production configuration, credentials, upstream calls, authority database access, services, deployment, and unrelated backend changes.
- Safety boundary: account-private portfolio data must not be exposed through a public namespace. If current query architecture cannot enforce that boundary, record the runtime query portion as blocked rather than guessing.
- Integration owner: `/root`.
