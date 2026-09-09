# limit4 fixed-release acceptance scripts ready

text_contracts / Mac. Only2new/tmp scripts; no repository/runtime/production edits. Parent executes after API/workers ready and Mac fixedmirror delivered. Explicit target release data-d976b04aee8b055ce929a4893b7d8e4f77e8126105da9142fb8016f176ea7c36; no CURRENT-following.

Cloud script /tmp/tushare-limit4-cloud-api-accept-20260909.py requires --release-id <target>. Defaultrepo/app root/data/tushare; default inputs validation/limit-extra-probe.json andvalidation/limit-range-probe.json. Confirms20probe observations in manifest, queries fourAPIs by bounded date/code groups against samefixed read_dataset, anonymous401/internal-auth, allcolumns and upstream_calls0. Internal-call secret only read inside parent-runcloud process, never printed. NoTushare client/capture. Output validation/limit4-api-acceptance.json (override--output).

Mac script /tmp/tushare-limit4-mac-offline-verify-20260909.py requires --release-id <target> --report <local extra report> --report <local range report>. Defaultrepo sharedmain/root existingmirror; output/tmp/tushare-limit4-mac-verified-20260909.json. Blocks sockets/DNS/get_secret. Verifiesprobe observations/raw/Parquets against manifestSHA, allsource columns and raw/request poolidentity. Independently deduplicates allfixedrelease rows in requesteddate scope using contractkeys+_row_identity, latest_fetched_at then_observation, and compares allcolumns toread_dataset. Reports rawprobe sum separately fromselecteddedup andfullscopequeryrows; noassumption1233 or975 equals queryrows. conceptts_code must equal source_ts_code andoriginal suppliercode; cloud sends rawconceptcode toquery filter. Defaultmax500partitions/API andlimit100000 failexplicitly instead oftruncating acceptance.

Prepared only: py_compile andboth--help passed. No runtimeAPI/Mac data验收 claimed. Parent owns execution, sync andfinal artifacts. ScriptSHA:
- /tmp/tushare-limit4-cloud-api-accept-20260909.py: aaeb0d8c802a0ac76ef0a2e71097c0879848e54057d134f6974cd1a7a03e694c
- /tmp/tushare-limit4-mac-offline-verify-20260909.py: 33d08ea4704e7d5598210cf5680088160b1d27a8c00c7669adc00b80cfe1bd0a
