# Post-79a2 three-batch publication gate

- Cloud authority has closed fund price batch 13, financial batch 18 and fund share batch 11: 1080 jobs, 942 done, 138 empty, 3102 unique physical references and 31204974 bytes. The read-only inventory recomputed every physical SHA256; its SHA256 is `4454d6ac5983cf5d3b7b5cb9223db6fd4d56d5cf35d161edd0beb719e6c4b1b0`.
- Mac remains on fixed release `data-79a2e1d0…`. The persistent verifier produced the expected negative control: all 3102 future references are absent, with zero manifest-metadata or local-physical errors, and exit 2. This proves the batches have not been mistaken for locally available data before publication.
- Normal publication is due after 2026-09-11 17:58:23 CST. No more exact batches will be inserted before that publisher. QuantMind, Tushare Worker and Beat are healthy; free space remains 115943481344 bytes above the 100 GiB hard reserve.
- A temporary inventory-export edit first failed Python parsing because of a missing newline, before opening the authority database. It was corrected, compiled locally and completed read-only with all hashes verified. No authority write or upstream request occurred in that failed attempt.

Next: observe the normal publisher, let the standard Mac LaunchAgent mirror the resulting immutable release, require all 3102 exact references and local SHA256 checks to pass, then run production-image reads with no network, empty tokens and a read-only mirror. Machine evidence: `docs/tushare-post-79a2-three-batches-publish-gate-20260911.evidence.json`.
