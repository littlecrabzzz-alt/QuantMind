# Technical history runtime baseline (before candidate deploy)

text_contracts read-only, business cloud-compose quantmind entry, SQLite mode=ro/query_only; no Pipeline constructed, no production writes. Script /tmp/tushare-history-budget-observe-20260909.py. Evidence /tmp/tushare-history-budget-before-20260909.json SHA256 e90b7eff1ac6f58466ab3758f2fcf56f8d2167926654f7cc15c1fb7a36f6f738.

Full frozen signature/identifiers retained in evidence. history:technical_extra anchor20260909 offset7500 done0 signatureSHA398150f7f9d5027d9271975f63f4e1696359008fa6c045a051725ffa000a5229. recent offset7500. All five target APIs have zero epoch=history jobs. Latest stored planning reports500 scanned,500 skipped recent,0 new; not evidence of historical collection. ConfigSHA0cab20b4bf875fc51f0b1eededd9e886799d3b5d084745a9d0a3106da4ff0864. Source /app/backend/shared/tushare_pipeline.py SHA a7801b24eff45d6daebaa4a2af06959eef912d638d96245db4b3b2a3d35bab9f.

Five API queries explicitly use existing jobs_partition_lookup(epoch,api) with group filter; EXPLAIN confirms SEARCH. At most20 job samples/API and3 attempts/job via PK; recent attempt tail200 via rowid descending (67486..67287). Per-query2s/overall15s SQLite cooperative budget, no long transaction; actual0.0041s. Statements are independent snapshots, not claimed atomic. No full jobs scan or MAX-rowid scan.

Await parent deployment/resume signal before after capture. Verify frozen signature continuity and absolute offset advancement; distinguish history enqueue from actual requests and preserve any sampling limitations. No manual job adjustment, Tushare probe or publish authorized here.
