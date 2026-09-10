# Tushare exact history wave 3

- Owner: Mac planning and release verification; cloud remains the only formal writer.
- Git: `master` is aligned on Mac, GitHub and cloud at `1fe6ee08` before this evidence commit.
- Production result: 962 upstream calls, 962 HTTP 200, 0 HTTP 429, 1,703,264 rows. Fund price batch 4 and dividend batch 3 are complete; announcement batch 2 ended at its 90-second budget and preserved all complete upstream payloads.
- Non-blocking exception: announcement task `8be3e259…` returned 6,000 rows and split correctly, but normalization hit the batch deadline. Its object and observation are durable; no Parquet was claimed. Continue other batches and let the split children cover the range.
- Runtime fix: Python startup now defaults LiteLLM to its bundled cost map. Host and Mac/cloud container tests pass; an actual cloud plan-only run starts without the unrelated remote cost-map warning.
- Publication boundary: `CURRENT.json` remains `data-051d825b…`; wave 2 and wave 3 are authority-only until the normal hourly publisher creates a fixed release. Do not read them from the Mac mirror yet.
- Next closure: stream the new immutable release manifest once, verify wave 2 and wave 3 task references and hashes, run the standard one-way Mac mirror, then prove an offline read with empty Tushare credentials and disabled network.
- Next exact work after closure: continue fund price and dividend history, continue pristine `anns_d` split leaves, and create a dedicated six-task `npr` historical-leaf batch rather than reusing the mixed refresh preparer.
- Capacity: 140,415,729,664 bytes free after the wave, above the 100 GiB hard reserve. Services are healthy with zero restarts and no OOM.
- Boundaries: `history_complete=false`, historical revisions and PIT are unverified, and RRG remains `blocked_data`.
