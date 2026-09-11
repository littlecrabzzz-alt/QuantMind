# Post-266b three-batch publication gate

- The cloud authority has 900 terminal jobs after fixed release `266b`: financial batch 20, index daily batch 9 and fund price batch 16. They contain 892 done and 8 empty jobs.
- A shared-lock, query-only export waited behind an ordinary acquisition. The no-revoke drain let that writer finish naturally; the export then recomputed every authority file SHA256. The inventory has 2692 unique references: 900 objects, 900 observations and 892 Parquet files, totaling 26546285 bytes.
- Direct `scp` could not read the root-only authority path. A read-only `sudo cat` stream transferred the same 489254-byte inventory with SHA256 `d3c4b59f5dfd676a59a7b22aeb4963e674822453a9ffff507feb9d816bdfd29d`.
- Mac remains on `data-266bb56d…`. The persistent verifier produced the expected negative control: exactly 2692 references are absent, with zero manifest-metadata or local-physical errors and exit 2.
- API, Tushare Worker and Beat are healthy. Free disk remains 113368154112 bytes above the 100 GiB reserve. The next normal publisher is due after 2026-09-11 21:13:10 CST; no more exact authority batch will be inserted before publication closes.

Next: observe the normal publisher, wait for the standard Mac fixed mirror, positively verify all 2692 references, and perform a no-network, empty-token, read-only production-image readback. Machine evidence: `docs/tushare-post-266b-three-batches-publish-gate-20260911.evidence.json`.
