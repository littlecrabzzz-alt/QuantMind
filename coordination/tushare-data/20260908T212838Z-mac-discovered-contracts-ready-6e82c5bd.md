# Discovered contracts ready
- Delta bb24b33, isolated codex/tushare-text merged b0e1845; only new discovered contracts/test/doc files.
- Live372/400 valid: DISCOVERED_CONTRACTS rt_k/rt_etf_k, full source+hidden fields, explicit snapshot epoch, current-only requests and no history fallback. Stock100-code batches, ETF documented patterns+all known outliers, source identities retained.
- Live188/422 now HTTP200 but23byte document-missing body, web+curl agree. DISCOVERED_GAPS only; no fake hk_hold/dc_concept_cons contract from old search caches. Parent should downgrade discovery current-doc verification, keep original cached evidence separately.
- Signatures iter_discovered_jobs(config,today,identifiers=None), discovered_prerequisites(identifiers=None,enabled_apis=None,config=None). Requires discovered_snapshot_epoch UTC YYYYMMDDTHHMMSSZ for Shanghai today. Family stocks/etfs. Contract keys contain generated _observation to preserve identical observations, never upstream.
- Integration not done: parent must enforce real-time authorization/expiry/actual timestamps before registering or scheduling. Independent permissions unprobed; no historical snapshots can be backfilled; ETF cap1000 operational only.
-6 offline tests prohibit socket/DNS, Ruff and git diff checks pass. No registry/pipeline/ledger changes or production/API calls.
