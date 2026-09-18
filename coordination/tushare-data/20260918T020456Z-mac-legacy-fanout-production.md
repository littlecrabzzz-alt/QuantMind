# Mac legacy fanout recovery production acceptance

- Owner/runtime: Mac archive owner at `~/Library/Application Support/QuantMind/tushare`; cloud full-archive writing remains disabled by `ARCHIVE_RELOCATED.json` and the cloud keeps only the research-cache timer.
- Code: `9f902617` whitelists retained-response recovery for `bc_otcqt`, `tdx_member`, and `kpl_concept_cons`; `52d67f0e` limits identifier discovery to the two OTC-bond APIs, three TDX APIs, and `kpl_concept_cons` respectively.
- Validation: 44 focused contract/deferred-split/runtime tests passed for the recovery change; 29 deferred-split and family runtime tests passed for the source projection. Ruff and `git diff --check` passed. The installed client imports the three reviewed APIs and the three source projections from the deployed runtime.

## Production evidence

All three pre-existing blocked caps reused their retained object and observation. No parent HTTP attempt was repeated: each still has one attempt and `tries=1`, and each recovery records `source_state=blocked` and `upstream_calls=0`.

| API | Child requests | Partition result |
| --- | ---: | --- |
| `tdx_member` | 616 | `identifier_fanout`, `universe_unverified` retained |
| `kpl_concept_cons` | 209 | `identifier_fanout`, `universe_unverified` retained |
| `bc_otcqt` | 761 | `identifier_fanout`, `universe_unverified` retained |

The first two recoveries ran with the earlier full identifier scan and therefore consumed the bounded acquisition deadline, producing local-only zero-request cycles. The installed `52d67f0e` projection recovered `bc_otcqt` and then continued normal acquisition in the same production cycle:

- cycle: `2026-09-18T02:01:43.540640+00:00` through `2026-09-18T02:03:25.195974+00:00`;
- real Tushare requests: 735;
- documents processed in parallel: 223;
- final states at cycle end: done 274754, empty 242960, pending 2890580, split_pending 7366, blocked 871, permission_blocked 4694, quality 564, resolved 5368;
- archive free space: 2487620960256 bytes.

One deployment bootout missed the five-second idle window and interrupted the next local identifier scan 33 seconds after the preceding completed-cycle status. It had not sent an upstream request or committed the remaining parent. Before redeployment, `PRAGMA quick_check` returned `ok`; `bc_otcqt` remained `blocked`, with one try, no recovery marker, no split, and no child. The only stderr entry was Python resource-tracker cleanup for five semaphores. The optimized worker then recovered that exact parent and passed the real-request acceptance above.

This closes the three reviewed legacy fanout gaps only. The child partitions remain incomplete until their requests finish, and observed identifiers do not prove the supplier's historical universe complete. The Mac full-history sync continues in the background; cloud full acquisition must remain disabled.
