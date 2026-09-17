# Mac Tushare batch throughput gray production result

- Production config changed only `batch_requests` from 400 to 700. `batch_seconds=100`, `archive_worker_cycle_seconds=105`, account and rollout ceilings remain 500 requests/minute, and the theoretical batch ceiling is 420 requests/minute. API-specific rate gates and daily quotas were not changed.
- Config SHA-256 changed from `aed7824e5bba72a2b1bf8c9e11a70b2da2320af4955dff04922d78bdecdc4f1f` to `f5785bb531ac22ecacd89d0ddbc77575b29a6baa5a17de6a4472c7c9be012795`. Rollback is `batch_requests=400`.
- The config fingerprint correctly triggered one production `planning_only` cycle at `2026-09-17T19:22:30Z`: 56.850 seconds, zero supplier calls, and no failed stage. This durable queue-maintenance stage was followed after the existing five-second minimum by real acquisition.
- Three real post-change cycles completed 407, 347, and 207 supplier requests in 100.815, 100.791, and 103.202 seconds. Every cycle had `failed_stage=null`; the LaunchAgent remained running as PID 68097 and its stderr stayed at zero bytes. Lower request counts remain possible when response latency or an API-specific gate is the active constraint.
- At the last acceptance cycle, coverage was 225,398 done, 205,012 empty, 2,874,034 pending, 425 quality, 6,093 split-pending, 873 blocked, 4,694 permission-blocked, and 5,676,517 superseded. These counts are a live checkpoint, not a completeness claim.
- Credential-free receipt: `validation/batch-throughput-gray-v1.9f831fabebe42e76118eaf181d1249871d30d69f9225d81e1f8eb5ad59e75709.json` under the Mac archive root. It records the rollback and both config hashes; `credentials_included=false`.

## Current scope audit

- The offline catalog/runtime audit reports 249 named scope APIs: 246 runtime-readable, two excluded mutations (`p_save`, `p_delete`), one SDK-only wrapper (`pro_bar`), and one public read contract still blocked because no authoritative callable contract is available (`ggt_monthly`). No registered API lacks a reader.
- The current immutable release `data-02a4b01dd61cf8b30c27efce1e57f79efcd46089eb074b7e1755103d2efd744b` contains planning coverage for 245 of 246 registered read APIs. The only registered API without its own plan is `p_get`; it depends on portfolio identifiers from `p_list`, whose fixed-release observation is available but empty. The audit therefore reports zero actionable registered-but-unplanned APIs.
- Of the 245 planned APIs, 196 already have published datasets. The remaining 49 are explicitly classified as 37 permission-denied, 11 provider API errors, and one available-empty-only result. These outcomes stay visible as coverage evidence rather than being mislabeled as completed data.
- Reproducible audit outputs were written outside the immutable archive: scope audit SHA-256 `cca83fe6130872cfb27972cde35e263b04cef7c49d97ecdd343de91ab7a741d2`; fixed-release audit SHA-256 `9349082d51dcfb9cbdc83088d21fdfca1618c0fe467f16c862fbeb0394eab55c`. The scripts and source ledger are versioned, so the one-megabyte derived scope JSON is not duplicated in Git.
- Historical completeness, field completeness, revisions, attachments, and point-in-time validity remain separate obligations. The local worker continues processing about 2.87 million queued partitions.

## Node boundary

- Mac remains the only full Tushare acquisition writer. Cloud remains fenced from provider acquisition and receives only the published research subset through the existing private read path.
- After this record was committed, `bash scripts/dual-node.sh handoff --align-git mac` passed at HEAD `9c795bbe089144295f8c2e3981ca27c21cf0b1f3` with source digest `ae871a873d490419aae7f2cd5e3703e04033b05963e6aa485df3201eab66b171`. On cloud, `tushare-research-cache.timer` is enabled and active; `data/tushare/ARCHIVE_RELOCATED.json` still records `source_paused=true` and the Mac hostname as archive owner.
