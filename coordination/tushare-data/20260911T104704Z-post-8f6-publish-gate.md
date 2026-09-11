# Post-8f6 four-batch publication gate

- Four exact manifests contain 1320 jobs. Only their 1077 terminal leaves are exported: 967 done, 110 empty, 243 pending. The terminal leaves form 1077 objects, 1077 observations and 967 Parquet files: 3121 unique references and 28848540 bytes. The authority export recomputed every physical SHA256; inventory SHA256 is `e00ea401166333c145f3a4f87c6e6e5b7d78a8d5ebccd87b8438166005a8d3ec`.
- The pending set remains explicit: fund-price batch 14 has 24, financial batch 19 has 219, including their two separate ReadTimeout leaves. Fund-share batch 12 and index-daily batch 7 completed at the 300-request gray tier with zero uncertain calls.
- Mac remains on fixed release `data-8f6c6d82…`. The persistent verifier produced the expected negative control: all 3121 future references are absent, with zero manifest-metadata or local-physical errors, and exit 2.
- Normal publication is due after 2026-09-11 19:04:17 CST. No more exact batches will be inserted before it. QuantMind, Worker and Beat are healthy; free space remains 114905370624 bytes above the 100 GiB reserve.

Next: observe the normal publisher, mirror the immutable release through the standard Mac LaunchAgent, require all 3121 exact references and SHA256 checks to pass, then repeat production-image no-network, empty-token, read-only reads. Machine evidence: `docs/tushare-post-8f6-four-batches-publish-gate-20260911.evidence.json`.
