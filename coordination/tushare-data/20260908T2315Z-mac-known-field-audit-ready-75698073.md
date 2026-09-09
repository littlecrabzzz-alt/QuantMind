# Known field audit ready — text_contracts / Mac

Scope: read-only 18 paid text/financial schemas; no runtime edits or production access. Isolated 0ea2e88 actual enqueue + main 1fba0bf offline capture/normalize. Current official doc HTML saved and hashed.

Result: zero current known output-table request omissions; explicit hidden fields already covered by catalog/extra/required. Confirmed synthetic capture gap: default-only financial VIP response loses requested hidden columns (income10/balancesheet6/fina_indicator59/express19) but sample_ok/missing_fields=[]; research_report file_name omission similarly unchecked. These are not claims of production loss. major_news src/src_site official ambiguity correctly triggers schema_gap in reproduction; keep as unresolved documentation/API evidence gap.

Evidence and exact no-token requests: /tmp/quantmind-known-fields-audit-20260909/audit.md, report.json, reproduction.json, provenance.json; official HTML by doc_id. Seven MockTransport cases with socket.connect denied.

Parent proposed integration: capture-only explicit request-vs-returned field coverage metadata, and otherwise-sample_ok nonempty missing-column cases become existing schema_gap. Preserve raw/source rows and all statuses with stronger meaning; no null filling, no historical rewrites, no automatic bulk retries. No implementation yet; parent notified before any shared intake edit. Worktree clean; no candidate commit needed for this read-only task.
