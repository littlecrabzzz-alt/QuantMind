# Post-473bf four-batch publication gate

- Four exact batches are closed in cloud authority: fund price 12, financial 17, index daily 6 and fund share 10. Together they contain 1440 tasks, 1284 done, 156 empty, 4164 unique physical references and 46566579 bytes.
- A read-only authority export rechecked every physical SHA256. The regenerable detailed inventory is 754981 bytes with SHA256 `2ba7e8182c160cc7349d1c501ad56ec54d008dc3a5064d083e3cbb0e02216fac`; the four durable batch manifests and task hashes are recorded in machine evidence.
- `CURRENT` remains `data-473bf47c…`. Normal publication is pending and next due at 2026-09-11 16:53:51 CST. Worker and Beat are healthy; no further exact batch should run before this publisher gets an execution opportunity.
- `scripts/verify_tushare_exact_release.py` was added as the durable acceptance entry point. Against old release `473bf…`, its expected negative control reports all 4164 references absent and zero metadata or local corruption errors.
- Acceptance still required: atomic cloud release, automatic Mac mirror, all 4164 exact references in the release with matching local SHA256, and offline readback under no network, empty tokens and a read-only mount.

Machine evidence: `docs/tushare-post-473bf-four-batches-publish-gate-20260911.evidence.json`.
