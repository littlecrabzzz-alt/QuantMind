# Post-35e exact-data publication gate

- The cloud authority has 818 terminal jobs created after fixed release `35e`: fund price batch 15, the two financial batch-19 recovery submanifests, and index daily batch 8. They contain 778 done and 40 empty jobs.
- A shared-lock, query-only export recomputed every authority file SHA256. The exact inventory has 2414 unique references: 818 objects, 818 observations and 778 Parquet files, totaling 22883575 bytes. It excludes the initial 141 financial batch-19 terminal jobs because fixed release `35e` already contains them.
- Mac remains on `data-35e0779…`. The persistent verifier's negative control reported exactly 2414 missing references, zero manifest metadata errors, zero local physical errors and exit 2. The inventory is 438599 bytes with SHA256 `1d8b67d91970866d573f9fef1e0337026947634b561ff62f80c8db6b1aeea05c`.
- API, Tushare Worker and Beat are healthy. Free disk remains 113928650752 bytes above the 100 GiB reserve. The next normal publisher is due after 2026-09-11 20:08:52 CST; no more exact authority batch will be inserted before this publication closes.

Next: observe the normal publisher, wait for the standard Mac fixed mirror, positively verify all 2414 references, and perform a no-network, empty-token, read-only production-image readback. Machine evidence: `docs/tushare-post-35e-three-work-units-publish-gate-20260911.evidence.json`.
