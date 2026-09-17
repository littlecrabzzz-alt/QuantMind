# Mac Tushare acquisition pipeline production acceptance

- Owner/data path: Mac archive owner at `~/Library/Application Support/QuantMind/tushare`; the cloud remains a research-cache reader and has no full-writer unit.
- Code: `2ec2203992182163d4f0dc5af4d91a8260e456ee` on local/origin `master` before this record. The change adds phase/detail timing, crash-safe two-deep prefetch, one persistent capture process, optional document-process isolation, and an installed LaunchAgent `ProcessType=Interactive`.
- Rate policy is unchanged: account and rollout ceilings remain 500 requests/minute; reviewed API-specific 50/120/200/240/300/400/500 limits, observed cooldowns, and daily quota ledgers still reserve before HTTP. Production keeps one HTTP worker and at most one prefetched request.
- Production config SHA-256 is `006a77d32048d55b095ac0d2c661c1ec809d6160165406fcf20ca960b70984f3`: `batch_requests=700`, `batch_seconds=100`, `archive_worker_cycle_seconds=105`, pipeline depth 2, capture execution `process`, document execution `process`, and two document download workers. Rollback receipts are private archive metadata and contain no credential.

## Diagnosis and rejected intermediate states

- Baseline profiled cycle: 384 requests/100.144s; `job_selection=60.759s`, capture 35.183s, result processing 3.882s. Read-only SQLite benchmarks showed selection queries were milliseconds, not the bottleneck.
- Nested timing showed almost all selection time was the durable account gate rather than its transaction: a representative cycle spent 63.835s in account-gate sleep and 0.290s committing 398 reservations.
- Thread depth 2 and then capture-process isolation were safe but did not improve throughput (roughly 385-413 requests/cycle). New timing proved requested account sleep near 39-41s became 86-89s in the LaunchAgent. Neither recent supplier result sets contained `rate_limited`.
- One-shot, no-network LaunchAgent probes reproduced macOS timer coalescing: a 120ms sleep had about 262ms median under default/Standard process type; `mach_wait_until` did not fix it. `ProcessType=Interactive` produced about 126ms median. This evidence replaced the unsuccessful thread-only hypothesis; the temporary probe and plist were removed.

## Production acceptance

- First full cycle after the LaunchAgent scheduling fix: 692 requests in 100.827s, 370 `sample_ok`, 303 `empty_unverified`, 19 `possibly_truncated`, no supplier rate-limit result, no failed stage, zero recovered or remaining in-flight jobs at the completed boundary. Requested/actual account-gate sleep was 70.276/75.206s. Documents completed 240 tasks.
- Second full cycle: reached the configured 700-request cap in 98.097s (about 428 requests/minute), with 390 `sample_ok`, 292 `empty_unverified`, 18 `possibly_truncated`, no supplier rate-limit result, no failed stage, zero recovered or remaining in-flight jobs at the completed boundary. Requested/actual account-gate sleep was 70.838/75.857s. Documents again completed 240 tasks.
- The first accepted cycle improved request count about 74% over the 398-request profiled cycle. The second cycle confirms the gain without adding concurrent upstream requests or relaxing any entitlement ceiling.
- Relevant offline suites passed: 115 acquisition/rate/worker/closure/deferred/index/timing tests, including real spawned capture and document processes against temporary storage/HTTP; the separate three-test cloud-drain suite passed with the system Python. Ruff and `git diff --check` passed on changed files.
- At acceptance the LaunchAgent was running with zero-byte stderr. Archive disk was about 3.996 TB total, 1.493 TB used, and 2.503 TB free. The queue remains intentionally unfinished and continues locally; a completed migration or throughput acceptance is not a claim that all historical data is present.

## Cloud boundary

- Before Git handoff, cloud `master` was still `2a37f0ba23bb331f1a4a8491b2284dbbb7db74ae`; `tushare-research-cache.timer` was active and enabled.
- The persistent stop-write marker exists at `/root/data/disk/quantmind/project/data/tushare/ARCHIVE_RELOCATED.json`; no `tushare-archive`, pipeline, or acquisition writer unit is installed. Code handoff must preserve this topology and must not restart full acquisition on the cloud.
