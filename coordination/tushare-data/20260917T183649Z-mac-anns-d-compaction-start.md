# `anns_d` saturation maintenance start

- Owner: Mac Tushare archive authority.
- Scope: preserve all announcement captures while retiring non-history capped roots after the same logical request has a canonical historical identifier fanout; recover legacy date-bisection parents whose children were already created before parent normalization timed out.
- Production evidence: 20 blocked non-history roots for `20260915` have the same 2,208 natural keys as the canonical historical root; the historical root owns 5,915 retained-code children. One separate blocked historical range already owns two exact date children.
- Safety boundary: no upstream request, response, attempt, object, observation, Parquet file, child edge, or unrelated job may be deleted. Changes will be developed in an isolated worktree, tested offline, deployed only after the running archive worker reaches a natural boundary, and then validated against the real Mac archive.

