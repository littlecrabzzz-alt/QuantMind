# RRG phase 2: conditional return diagnostics and price-definition gate

Scope: user explicitly requested continuing RRG research and viewing progress in the existing page. Mac local sandbox only; no cloud results publication, source mutation, strategy/model registration, upstream data call or trade.

Outputs: `/Users/lizeyu/Downloads/QuantMind-RRG-phase2-20260912/`. Core manifest SHA256 `9d73c3a697f5e48afbb3c014dce68e014f9d4363dc7ebf98899c3dfa11c5d90f`. Phase 1 immutable artifacts retained. Existing local RRG draft discussion now contains a phase 2 results message, without executing the stock-model template. One discussion-only model request was queued through normal UI.

Fixed release `data-6e00837911a40223d75d7e4e7b770b4b60b4b7c9f2d208091c6e343f7283bee6`; 28 sectors, 2022-09-01..2026-08-31, 220/60/20. Separate frozen next-close hypothetical-index diagnostic, plus explicitly unverified next-open sensitivity; original project protocol unchanged. Monthly drift, cash, post-fee self-financing, 10/20/30 bps. 18 combinations and independent daily accounting pass; max error 1.11e-15.

20 bps next-close primary CAGR equal-weight/momentum/RRG 7.91/7.03/10.48 percent; RRG drawdown -30.97 percent vs momentum -28.98; latter half relative growth -1.06 percent. All 3 costs fail the predeclared improvement gate. These are conditional diagnostics, not formal return proof.

NEW PRIORITY: 180 raw objects / 38580 records exactly match stored OHLC/pre_close/pct_change. Yet doc308 still says open/high/low no longer disclosed. More seriously, preceding stored close vs pre_close differs >5 bps in 133 rows across 30 sectors, 108 rows in the 28 used. Concentrated 2025-07-22 (27 sectors), 2026-07-27 (28), 2026-08-27 (28). Maximum 16.2233 percent. Do not silently patch or infer cause: index rebasing/divisor/revision/field semantics needs authority evidence.

Post-discovery separately frozen sensitivity keeps signals fixed and chains pct_change for hypothetical valuation (not corrected full RRG). 20 bps CAGR becomes 5.15/3.79/7.96 percent, latter-half RRG relative growth changes to +2.02 percent. Data definition materially changes interpretation. Full source issue table and author snapshot comparison in `price-sensitivity/`.

Next gate: authoritative explanation/independent source reconciliation of those dates and CI005001/003/014/029 (retain all 28); only then pin a new accepted version and recompute signals from warmup plus returns. Keep `blocked_data`; no parameter optimization or broad acquisitions. PIT industry revisions, breadth membership known_at and ETF execution remain separately unverified. Research-agent-product backend/frontend ownership untouched.

Completion update: Both discussion-only calls completed; latest page response correctly states phase 2 conditional simulation complete and formal validation not passed. Latest local release 85ffcb29 checked on 180 paired records for issue dates and prior sessions; open/close/pre_close/pct_change unchanged. Full evidence and delivery manifest saved. No backend/frontend edits.
