# Tushare realtime10 / document claim v2 / RRG bridge production closure

- Integrator: root; master `47a2f0df8a09d4794f01a5bf3b349e93dc92ae3d` was pushed and dual-node handoff passed with 5933 files, source digest `5b85e9ce0f3b139176d07f9b10a78d654bb333e33413a6aad7ee0f3e25422f3e`.
- Realtime10 exact permission probe: 10 upstream calls, every exact API permission_denied, no config/enable change. Probe SHA `62ee99ff...`, fixed `data-95fde4...`, cloud/Mac report SHA `f3fb4f99...`, equivalence `aa1d3297...`.
- Only Tushare acquisition/document queues were drained. Online SQLite backup SHA `ccd423f4...`; claim schema v1 to v2 and pending partial index deployed. Five accepted tasks processed 52/82/100/19/37 documents; claim DB work remained about 29-38ms/call. Two acceptance reads collided with claim writes, and later tasks recovered; SQLite read/write contention remains open. Final superseding acceptance SHA `22da2d21...`.
- Seven RRG contracts loaded in production and all existing RRG jobs request complete catalog field sets; audit SHA `f71e99b6...`. Mac fixed bridge remains blocked_data; report/artifact SHA `9a21f125...`/`a5984bfc...`.
- Follow-up remains unbounded: attachment backlog, historical completeness, source revisions/PIT, authoritative CITIC membership time and exact historical ETF PCF. Preserve cloud data authority and fixed-release Mac reads.
