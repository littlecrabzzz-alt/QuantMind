# Mac fund_basic pagination rollout start

- Node: Mac archive authority
- Scope: recover the saturated `fund_basic` off-exchange active-fund catalogue without discarding retained responses.
- Official contract: `market`, `status`, and exact `ts_code`; published single-call maximum is 15,000 rows.
- Live evidence: the provider accepted `limit` and `offset`; stable repeated 100-row pages differed by offset; offset 15,000 returned 10,042 rows with `has_more=false`; offset 30,000 returned zero rows.
- Retained-page comparison: the existing 15,000-row page and the live tail contained 25,038 unique codes with four cross-page duplicates. Dataset normalization must deduplicate by the reviewed `ts_code` key.
- Boundary: no credential is recorded. Cloud remains research-cache-only and must not run the full writer.
- Deployment: wait for the Mac worker's natural cycle boundary, install from merged master, then atomically reuse each retained legacy page zero and enqueue its page at offset 15,000 with zero repeated upstream calls.
