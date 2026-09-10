# RRG ETF acquisition batch preparation ready

- Branch: `codex/rrg-acquisition-prep`
- Candidate: `41075320`
- Base at commit: `5083e920674615cb61c3d473334c6e31c71b1ff7`
- Fixed source: RRG audit report SHA256 `74d6798cab10c1ead48eca23927a511bd7192c882c8855c20b1df8f4737e1fe6`, collection plan SHA256 `e03f273adc3c6448de8deff835f214a36d7e04a1ff8bcea1a37a1b2c84f10030`, release `data-03885aef45ce7be5ce812f4305734a7c8852646a09cfa567383215d10e5f6d22`.
- Prepared: 1,718 fund_div per-ETF history tasks plus 49 etf_limit history month windows; eight deterministic shards, 1,767 Pipeline task IDs total.
- Excluded: 1,888 fund_daily diagnostics unless explicitly requested; all 5,774 PCF tasks remain blocked by missing authoritative historical ETF-industry mapping.
- Semantics: Pipeline empty is a terminal request receipt only; no no-dividend, suspension, opening-tradability or PIT inference. No price filling.
- Idempotency: two isolated runs produced byte-identical shards and batch-manifest SHA256 `3ceaa518a73af92df4c824a9fa2c4fc7a65343a75569396643b749b091927d81`.
- Isolation: temporary Pipeline identity database only; no production DB, Token, network, upstream call, enqueue, enablement or fixed release publication.
- Validation: nine related unittest cases, Ruff, JSON and diff checks pass.
- Next gate: after merge and separate authority authorization, implement/review a lock-aware per-shard importer that calls existing Pipeline.enqueue and verifies returned task IDs; run existing workers and publisher only in the production window.
