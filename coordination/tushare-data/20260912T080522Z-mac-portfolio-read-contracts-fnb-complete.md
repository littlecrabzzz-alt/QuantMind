# Tushare portfolio read runtime candidate complete

- Owner: `/root/financial_next_batch`
- Base: `21c49a2d842101f50646f79bd853b530a956f6b6`
- Branch: `codex/tushare-portfolio-read-contracts`
- Commit: `92cf388ab9db3bd867697bba5ca623826e7d9663`
- Worktree: `/private/tmp/quantmind-portfolio-read-contracts`
- Scope: default-disabled runtime and fixed-release query registration for official read APIs `p_list` (doc 446) and `p_get` (doc 449) only.
- Mutation exclusion: `p_save` and `p_delete` remain absent from registry, planner, fixed reader, and mirror query contract.
- Planning: explicit snapshot epoch; unfiltered `p_list` first; `p_get` only from the latest durable, successful, same-epoch `p_list` observation. No configured or guessed names.
- Identity: real `_observation` plus request identity and raw row identity; user-defined `ts_code` is preserved without stock normalization. Fixed query metadata marks the dataset `account_private`.
- Official limits: docs publish no pagination, row cap, request frequency, history range, or entitlement rule. No pagination was added; local 1000-row cap remains an unverified conservative saturation guard.
- Production effects: none. No credentials, upstream calls, authority access, service operation, deployment, or production config changes.
- Validation: direct portfolio suite 9 passed; adjacent registry/pipeline/store/rate/scope/mirror group 56 passed; Ruff and `git diff --check` passed.
- Full Tushare discovery run: 1167 tests, 3 failures, 5 skipped before the final related expectation repair. The portfolio-related legacy scope failure was fixed and passed in the 56-test rerun. The two remaining failures concern the pre-existing `fina_mainbz_vip` named-scope/rate fixture mismatch, outside this candidate.
