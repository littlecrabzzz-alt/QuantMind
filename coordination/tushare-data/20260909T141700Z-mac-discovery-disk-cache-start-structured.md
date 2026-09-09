# Bounded derived discovery disk cache candidate

Owner structured, independent worktree quantmind-tushare-structured, branch codex/tushare-discovery-disk-cache based 745e0a6. Own only new backend/shared/tushare_discovery_cache.py, Pipeline.identifiers narrow cache context, scripts/test_tushare_discovery_cache.py and candidate doc. records stays byte-for-byte unchanged. Text confirmed its account runtime imports/normalize/plan validation hunks do not overlap. No production/config/upstream operations.

Complete jobs UNION attempts membership + eligible source stat remains each call. Cache is rebuildable/default off, 128 MiB SQLite bound, 256 KiB page cache; each call bounds new admissions at 0.5 s plus one <=2 MiB projection. Request-aware sources bypass. Corrupt/full/missing/stale cache falls back to authoritative raw. Nine temporary-fixture tests pass; full retained fixed-mirror baseline/cold/cross-Pipeline warm equivalence and capacity/RSS validation running under /tmp/tushare-discovery-disk-full. Final candidate/evidence to follow in this record.

## Ready, local only

Read shared AGENTS at 6b18287: project sharing remains future work; existing Tushare fixed releases flow cloud to Mac. This cache remains node-local and is never mirrored or promoted to source data. No production reads/writes, source HTTP, configuration or source-refresh changes occurred in this candidate.

Committed/pushed `b78953f8c6ff43f7c3c23fb994c5fab8be6f869e` plus `08a54f6` on `codex/tushare-discovery-disk-cache`. Five owned paths: new cache module/test/doc, identifiers-only pipeline hook, mirror installation copy-list one line. records and other class methods unchanged by AST comparison. The follow-up single runtime line explicitly releases the prior projection before decoding the next object; weakref test proves lifetime rather than inferring it from RSS. Parent owns integration and opt-in after production resource review; no runtime activation here.

Python 3.10: 42 focused/adjacent tests passed in 1.575 seconds. Command: `PYTHONPATH=scripts /tmp/quantmind-calendar-factor-test310/bin/python -m unittest test_tushare_discovery_cache test_tushare_discovery_projection test_tushare_discovery_timing test_tushare_history_minutes_pipeline test_tushare_mirror_install`. git diff --check passed. Tests include old default, cross-Pipeline reopen, complete metadata membership/revisions/deletion/DB restore, object stat and extractor invalidation, request-aware bypass, pair association, malformed raw failures, error-persistent metrics, fixed cap/zero-admission, corruption/oversized decompression, busy SQLite, source changing during admission, foreign DB/symlink rejection, and previous-list lifetime.

Fixed input: `data-33a0a39081f1fd12ff0e2b471671010add90dac48b35eadc0ac42412b5d92971`, Mac immutable mirror. All 80,517 observations SHA-checked; current 118-API discovery mapping selected 20,217 source objects / 667,677,169 bytes, also raw SHA-checked. Full membership preserved; this is observation-derived fixed-mirror scope, not a copy or claim of current live jobs/attempts completeness. All measured IDs SHA = `8b700e3eed99082b2a43e0204bc8ce38bb307834907c2c403bba49673b4ed766`. Socket/DNS/secret access blocked. Temporary metadata/cache only; immutable files never modified.

At b78953f, 15 full-set baseline/cold/12 warm/reopened-Pipeline/control passes all equal: baseline 9.5845 s, cold 9.7478 s, warm12 6.6626 s, immediate disabled control 8.3198 s (~19.9% lower on that adjacent Mac comparison). Warm12 had 3,631 hits and 15,340 raw reads, so no fully-warm or source-free claim. DB 27,721,728 B; process ru_maxrss 356,286,464 B; external sampled RSS 353,124,352 B; 230-second/512-MiB guard not reached. Report `/tmp/tushare-discovery-disk-reviewed/report.json` SHA `12dc0c336f4dc9766e83f1b7221d2906bb0f4dafe9acfb27af64b4d0ef36eb27`. Supervisor SHA `42c0c7791b98c15a3306b3a4b0444812fb1677974007d0093399711350b8b053`. Re-run entry `/tmp/tushare-discovery-disk-reviewed-supervise.py`.

Final 08a54f6 lifetime-fix recheck uses the same complete fixed collection, baseline/cold/two fresh Pipeline warm/control passes; all IDs equal again. Results:
```json
{
  "runs": [
    {
      "mode": "baseline",
      "seconds": 9.58571591693908,
      "raw_reads": 18971,
      "cache_hits": null
    },
    {
      "mode": "cold",
      "seconds": 10.49158287490718,
      "raw_reads": 18971,
      "cache_hits": 0
    },
    {
      "mode": "warm1",
      "seconds": 9.218943832907826,
      "raw_reads": 18902,
      "cache_hits": 69
    },
    {
      "mode": "warm2",
      "seconds": 9.172196875093505,
      "raw_reads": 18470,
      "cache_hits": 501
    },
    {
      "mode": "baseline_after",
      "seconds": 8.77497037500143,
      "raw_reads": 18971,
      "cache_hits": null
    }
  ],
  "cache_files": {
    "discovery-cache.sqlite": 4890624
  },
  "ru_maxrss_bytes": 339673088,
  "supervisor": {
    "exit_code": 0,
    "guard_reason": null,
    "monitored_peak_rss_bytes": 336887808,
    "rss_limit_bytes": 536870912,
    "elapsed": 62.22898091701791,
    "seconds_limit": 230
  }
}
```
- `/tmp/tushare-discovery-disk-lifetime/report.json` SHA `aaadcd7a60627f63c58bf1947ab18b9dc578c0fb7a7c70ce2e6e24ca66d901e8`
- `/tmp/tushare-discovery-disk-lifetime/supervisor.json` SHA `0379027242205fe0085757d50878364d51bf1a29dbdce4813a49bbb0c3a64d2d`
- `/tmp/tushare-discovery-disk-lifetime-benchmark.py` SHA `69a676313720d723afbbc23f1b91ac9445b891cd00ab41341ebe92a55897dc27`
- `/tmp/tushare-discovery-disk-tests-final.log` SHA `aef55a07610f5e943aac637ae960ac480a6be703c35bc56197c57384b16d4356`

Re-run final evidence via `/tmp/tushare-discovery-disk-lifetime-supervise.py`. Code SHA recorded inside each report matches its stated candidate; the 12-warm timing belongs to b78953f, not a production run. The final delta changes object lifetime only; do not attribute an unmeasured production RSS reduction to it.

Limits: default OFF; 128 MiB cache file cap/256 KiB SQLite page cache and 2 MiB decoded entry; gradual per-call 0.5 s admission plus last bounded entry. Full metadata/stat scans and request-sensitive raw reads remain. Cache saturation/corruption fall back to original reads, with no membership truncation. No cache eviction or cross-node synchronization. Mac RSS does not measure cloud cgroup/file-cache pressure, source latency, or total batch throughput; production still needs a limited opt-in check. Candidate ownership released.
