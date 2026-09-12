# Risk2 official-sample cloud evidence closure

- Observed at: `2026-09-12T07:43:48Z` (`2026-09-12 15:43:48 +0800`)
- Deployed quota code: `d61e93d6`
- Scope: read-only exact-PK and immutable-file verification, followed by the two explicitly authorized create-only validation artifacts. No probe, enablement, configuration change, release publication, service action, or credential read occurred.

## Execution evidence

- Report: `validation/risk2-official-sample-20260912.json`, 1,415 bytes, SHA-256 `820ac50b20be6217a20525d25187c8634bbdb45123585db34c79fc4c02426114`
- Receipt: `validation/risk2-official-sample-20260912-receipt.json`, 363 bytes, SHA-256 `34b5c6bc95c02113828ba83f38a08e1a951117a451431d3fd1cd2576fbcb3ef4`
- Exact pipeline rows: 2 jobs and 2 attempts. Each task has `tries=1`, attempt `1`, HTTP `200`, `response_complete=true`, `row_count=0`, state `empty`, and status `empty_unverified`.
- `stk_alert` task `c4ef2d954567137de1c1b5431359ae03d5d0a32376f8a3750f7a827a6d78e81d`: `start_date=20260316`, `end_date=20260316`.
- `stk_high_shock` task `5c1f28116cbfff6104a8f2a997021e8b06f76b7b678398bdb540a58afbcd25dd`: `trade_date=20260312`.
- Actual upstream calls: 2; report elapsed time: 0.226 seconds.

## Exact immutable references

- `objects/a94bf19f7f50a29b8fd9fb7375e1d833da3a44384c17cb396f88ed5ebd8f21e0.json`: 192 bytes, SHA-256 equals object name.
- `observations/b5c6e7f13f4f44ebacbd2c93f450ad27.json`: 856 bytes, SHA-256 `83c695c72bab30453fb3a9b582d39f6da4fd85dcd744dbb5b8b9be0539ae9de8`.
- `objects/291edfa1908f0e6321e41f77ac80b4adda7927fd6ec41b2505a80e3182cbdc70.json`: 207 bytes, SHA-256 equals object name.
- `observations/cab8b45a9f5440e98ee8a1f9a3f6d959.json`: 869 bytes, SHA-256 `8cba54860d62e56658e933de612f9b30375dd505945275e3b45029bac471798b`.
- Total: 4 unique references, comprising 2 objects and 2 observations, 2,124 physical bytes. A second independent read recomputed every file's byte count and SHA-256.

## Publication boundary and create-only artifacts

- CURRENT remained `data-de494289775ece674a54bb560ac3ecad37187af6ed1ef69f8590b78ddbbb3fb0` while the shared lock was held. Its manifest SHA matched the release identity, and none of the four exact references was present.
- Inventory: `validation/risk2-official-sample-20260912-exact-refs.json`, 1,438 bytes, SHA-256 `f535ff4f0f8eb5301809968eeb43e2a719d3b2b50be1df81344fb67eb906283f`.
- Closure: `validation/risk2-official-sample-20260912-closure.json`, 2,095 bytes, SHA-256 `c2591b9770676320cb02da6c5a0a9fe4c38accd266444d0e865c2d1fa32ce729`.
- Publication target is strictly after captured release `de494`, through the next normal publication. This evidence does not authorize a special/manual release.

## Semantic boundary

Both responses are retained only as complete empty observations for the exact sample requests. They do not establish historical completeness, historical versions, point-in-time validity, or absence of events. The official-document sample/output date inconsistency remains a `source_consistency_gap`; automatic enablement remains false.
