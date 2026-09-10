# Tushare realtime, RRG and document production completion

- owner: mac
- role: code/config development and read-only mirror verification
- status: completed for this bounded production batch
- branch: `master`
- code head used in production: `d75353c16d2092ed2a16380fbf141434dd048db9`
- code source digest: `57d3ca92b6b44c46fe47212577448a57e81c2d201f8fa94b710eeb988dd057d3`

## Accepted changes

- Added bounded `PdfReadError` lenient fallback inside the existing 15-second parse subprocess and deployed it to the dedicated document worker.
- Added and ran the bounded realtime/TMT probe. Five real calls produced one `rt_min` sample, two explicit ETF permission denials and two invalid TMT API responses. No API was automatically enabled.
- Added and ran the exact RRG acquisition batch runner against the immutable 1767-task manifest. It made 360 calls in 69.23 seconds and did not publish or switch `CURRENT`.
- Published and mirrored fixed release `data-6c9f0b0b777f5edfbb3654809006b01ea22770dd23fce20839be1a9be0d20ab1` with 574380 files. Mac read `rt_min` offline with upstream access disabled.

## Verification

- Python 3.10 Tushare suite: 951 passed, 5 skipped.
- Changed-file Ruff checks passed. Four pre-existing UP038 suggestions remain in the full pipeline module.
- Both dedicated Tushare workers are healthy; an ordinary acquisition task completed after restart.
- Cloud available bytes: 158941462528; stop threshold: 107374182400.
- Production evidence: `docs/tushare-realtime-rrg-production-20260910.evidence.json`.
- Evidence SHA256: `0e332138791537481ad05c472d156ac194c7f434aa623711b6270a0e4dd93d45`.
- Immutable RRG receipt: `/data/tushare/validation/rrg-exact-batch-20260910/receipt-f80427372d3dc2b9.json`.
- RRG receipt file SHA256: `bd4a0e3bb4c4f6711b560b63a178db4e6375b50ee5006639cd33d889c4e6cca2`.

## Remaining work

- Continue the multi-million structured backlog and million-scale document backlog through the existing bounded workers.
- Preserve explicit permission and invalid-API outcomes; do not auto-enable denied ETF or invalid TMT endpoints.
- Keep `rt_min` out of research admission until historical/session/PIT and unit semantics are verified.
- Keep RRG `blocked_data` until member `known_at`, versioned ETF-industry mapping, price/tradability/dividend/PCF coverage and research acceptance are complete.
- Continue observing planning and publication tails near the 160-second Celery soft limit.

No credential, token, order, payment record or raw secret is recorded here. Cloud remains the formal data writer; Mac remains a one-way read-only mirror.
