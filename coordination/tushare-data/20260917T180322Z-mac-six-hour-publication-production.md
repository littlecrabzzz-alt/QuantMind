# Mac six-hour publication cadence production acceptance

- Time: 2026-09-17T18:03:22Z
- Archive owner: Mac
- Source commit: `0e720c9e`
- Archive root: `~/Library/Application Support/QuantMind/tushare`

## Measured bottleneck and decision

The hourly production publication that started at 2026-09-17T17:47:48Z completed normally as `publish_only` with zero upstream calls. It took 527.494 seconds end to end and 461.929 seconds inside publication. The immutable manifest was 456,697,375 bytes.

Measured publication stages included 214.867 seconds for `metadata_inventory` and 180.282 seconds for `scan_attempts_and_stat`. Repeating this full scan every hour would spend about 12.8% of the single archive worker's wall time on fixed-release construction rather than acquisition.

The production `publish_interval_seconds` was therefore changed from 3,600 to 21,600. The 900-second planning cadence, 105-second worker cadence, all account/API rate limits, daily caps, disk reserves and the single-writer boundary remain unchanged. Explicit manual publication remains available when a research input must be frozen immediately.

API raw objects, observations, Parquet and attempts remain transactionally persisted before fixed-release publication. The operational tradeoff is up to roughly six hours of fixed-release visibility lag while full local synchronization is active.

## Safe configuration update

- Config hash before: `4913c30f6a7e1dfae9928d30c3b2ce2c8b19108efd02b0a58d8a56f49a2a384a`.
- Config hash after: `aed7824e5bba72a2b1bf8c9e11a70b2da2320af4955dff04922d78bdecdc4f1f`.
- Config file mode: `0600`.
- Update method: same-directory atomic replacement with file and directory sync.
- Worker restart required: no.
- Upstream calls made by the update: 0.
- Private receipt: `publish-cadence-update-v1.00c3052c3d798f11743d56e7683af77e918f8ba19ebc6c4a96fed096f5ffcd7e.json`.

The first cycle that read the new config completed at 2026-09-17T18:01:05.550119Z as a real `planning_only` cycle with reason `configuration_changed`. It made zero supplier requests and did not rebuild the fixed release.

## Real acquisition acceptance

The immediately following cycle completed at 2026-09-17T18:02:51.200656Z:

- Publication interval reported by the running worker: 21,600 seconds.
- Publication state: `deferred`, mode `acquire_only`.
- Next automatic publication due: 2026-09-17T23:55:30Z.
- Real Tushare requests: 362.
- Cycle elapsed: 100.603 seconds.
- Queue: done 217,336; pending 2,862,113; blocked 1,177; quality 339; split-pending 5,903.
- Worker PID: 35101; state active/running; last exit code absent; stderr size 0.

`CURRENT.json` remained on `data-02a4b01dd61cf8b30c27efce1e57f79efcd46089eb074b7e1755103d2efd744b`. Its pointer hash, release identifier and recomputed 456,697,375-byte manifest SHA-256 all matched. `PRAGMA quick_check` returned `ok`.

At the measured 461.93-second publication cost, skipping five redundant hourly scans releases about 2,310 seconds per six-hour window for acquisition. This is a capacity estimate rather than a request-throughput promise; the real post-change cycle above proves that acquisition resumed under the new cadence.

Mac remains the only full Tushare archive writer. Full local historical synchronization remains active and incomplete.
