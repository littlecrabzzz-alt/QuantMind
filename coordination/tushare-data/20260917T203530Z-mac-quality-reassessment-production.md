# Mac retained-quality reassessment production acceptance

- Time: 2026-09-17T20:35:30Z
- Archive owner: Mac
- Code commits: `f5f00ee0ca3629d5983d878be9ad65a8041cfba9`, `5ce7e1356c14bdbefaa080b478862b810e88860d`
- Archive root: `~/Library/Application Support/QuantMind/tushare`
- Runtime root: `~/Library/Application Support/QuantMind/tushare-client`

## Reviewed boundary

The first full dry-run found one retired `dc_member` replacement parent with a retained object and observation but no Parquet because the original normalization ended in `SoftTimeLimitExceeded`. The old reassessment helper treated this intentionally retired parent as an active quality candidate and aborted the whole batch before mutation.

The helper now skips a blocked parent only when its split row is also blocked, its `gap` equals the evidence `replacement_gap`, and that value belongs to the reviewed replacement-gap set. It reports the row as `retired_replacement`. Ordinary blocked and quality candidates still require complete object, observation and Parquet references and full SHA-256 verification; corrupt active evidence still aborts the transaction.

The quality audit also distinguished retained source gaps from stale contracts. Responses with null `cctv_news` content, null `fund_portfolio` market value, or other non-null core fields remain explicit `schema_gap` records. Their immutable response and normalized Parquet are retained in the archive and release inventory; they are not relabeled complete. One legacy `etf_basic` job was different: its old job contract rejected null `list_date`, while the current reviewed contract already treats every ETF metadata field except `ts_code` as nullable. The explicit assessment override applies that current nullability only during evidence-preserving reassessment.

## Tests and production transaction

- 5 focused reassessment tests passed after the retired-parent fix.
- 12 reassessment and RRG contract tests passed after the ETF compatibility update.
- Python compilation and `git diff --check` passed.
- Full current-contract dry-run: 1,370 candidates; 621 `dc_member`, 142 `moneyflow_dc`, and one `index_weekly` retired replacement parent were conservatively skipped; no job was promoted under the unchanged contracts; upstream calls 0.
- ETF-only dry-run: 2 quality candidates; exactly one promotable and one old response without the complete response metadata required for reassessment.
- ETF-only apply: one job changed from `quality/schema_gap` to `done/sample_ok`; its source attempt, tries, object, observation and Parquet were preserved; upstream calls 0.
- Immediate idempotency dry-run: zero promotable jobs; the metadata-incomplete legacy row remains an explicit quality gap.
- Private receipt: `contract-reassessment-v1.ab085289c2fc1b30772b5b64c79716bf535feb26b2f24e08cb40ff4f31ed9e5b.json`.

## Worker continuity

LaunchAgent `com.quantmind.tushare-archive` resumed as PID 97791. The first complete post-maintenance production cycle ended at 2026-09-17T20:35:30.685284Z:

- Real Tushare requests: 299.
- Cycle elapsed: 101.071 seconds.
- Failed stage: none.
- Queue: done 232,245; empty 209,345; pending 2,879,609; blocked 874; permission-blocked 4,694; quality 524; resolved 4,217; split-pending 6,300.
- Documents processed: 240; document status `ok`.
- Worker stderr: empty.

The Mac remains the only full Tushare archive writer. The cloud node remains restricted to the research cache.
