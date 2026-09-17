# Mac Tushare retained-contract reassessment production rollout

- Time: 2026-09-17T09:15:51Z
- Archive owner: Mac
- Code commit: `b9c450d1` (`Reassess retained Tushare quality records`)
- Archive root: `~/Library/Application Support/QuantMind/tushare`
- Runtime root: `~/Library/Application Support/QuantMind/tushare-client`

## Production change

The rollout re-evaluated retained successful payloads with the current field contracts. It did not call Tushare, replace source attempts, or copy Parquet data. Every promoted record first passed size and SHA-256 verification for its object, observation, and Parquet artifacts. The immutable source attempt remains available with its original assessment.

- Candidates verified: 931
- Promoted to `sample_ok`: 767
  - `research_report`: 762
  - `ci_daily`: 5
- Retained as real quality gaps: 164
- Upstream calls during reassessment: 0
- Attempts present and preserved at apply time: 380,939
- Receipt: `contract-reassessment-v1.b3c1b6e4589297ae9a596feaafbbbef4b3de46bbd4f2b73a24f78475623c21ba.json`

The post-apply database contained 767 overlay rows and 767 `done` jobs carrying `contract_reassessment.reassessed_status=sample_ok`. A sampled promoted job retained its original `schema_gap` attempt. The complete quality state after the transaction contained 176 jobs because additional non-candidate quality states remain; `cctv_news` accounted for 108. No remaining quality row was promoted without satisfying the current contract.

## Publication

- Release: `data-a1ad063610926889d6d2fda87df07fa035bd16040022a158eb9452328d27c7cf`
- `CURRENT.json` identity: verified
- Reassessment-marked datasets: 767
- Distinct reassessed Parquet paths: 767
- Marker APIs: `research_report=762`, `ci_daily=5`
- Marker quality state: `sample_ok=767`
- Marker upstream calls: `0=767`
- Promoted job IDs still present in manifest gaps: 0
- Manifest quality gaps: 176, matching `coverage.quality`
- Manifest inventory: 201,071 datasets and 1,504,437 files
- Full `verify_data` object checksum pass: passed
- Publish stage failure: none
- Publication upstream calls: 0

The production publication held `.archive-worker.lock`, `pipeline.lock`, and `documents.lock`. It wrote the immutable release and atomically changed `CURRENT.json`. Total elapsed time including full read-back verification was 512.792 seconds.

## Real acquisition acceptance

After publication, LaunchAgent `com.quantmind.tushare-archive` resumed with PID 60350. The first complete acquisition cycle reported:

- Status: `completed_cycle`
- Requests: 263
- Preserved attempt rows in the cycle: 297
- Result assessments: `sample_ok=134`, `empty_unverified=156`, `possibly_truncated=7`
- Transport, rate-limit, permission, API, invalid-response, and invalid-value errors: 0
- Acquisition failed stage: none
- Document processing: 240, status `ok`
- Elapsed: 101.427 seconds
- Pending after the cycle: 2,961,228
- Account ceiling: 500 requests/minute
- Final API-specific gate in the cycle: `report_rc`, 300 requests/minute

The worker continued into subsequent production cycles. QuantDB was not stopped or modified by this rollout.

## Validation

Passing test files before deployment:

- `scripts/test_tushare_field_coverage.py`: 11 passed
- `scripts/test_tushare_contract_reassessment.py`: 3 passed
- `scripts/test_tushare_intake.py`: 7 passed
- `scripts/test_tushare_pipeline.py`: 17 passed
- `scripts/test_tushare_text_contracts.py`: 7 passed
- `scripts/test_tushare_anns_d_saturation.py`: 5 passed
- Ruff checks, compileall, and `git diff --check`: passed

Known pre-existing failure, reproduced on the untouched base and this change: `scripts/test_tushare_manifest_serialization.py::test_multiple_c_chunks_and_default_python_fallback_have_exact_bytes` expects `timing["eager_chunks"]` to be false. It was not introduced by this rollout.

## Capacity and remaining work

- Local filesystem size: about 3.6 TiB
- Used: about 1.3 TiB
- Available: about 2.3 TiB
- Full historical synchronization remains active and incomplete.
- Remaining stale invalid-shape blocked jobs require replacement-coverage proof before retirement; they were not silently marked resolved in this rollout.
