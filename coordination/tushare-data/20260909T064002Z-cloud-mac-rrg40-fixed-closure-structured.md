# RRG40 fixed cloud/Mac closure verified

- Task structured, read-only; old priority operation rrg-diffusion40-20260909-b0b0f1b914894a928565212be8f0fd28. No new upstream, priority/config/cursor/DB writes or publish.
- Fixed release `data-ca7c1fcb7305d3248b3d820714c4b868087e0fbf66facf2bd17e00cded0c2001`; all 40 sample_ok targets / 217026 source rows, no pending/unpublished/failed. 120 raw/observation/Parquet paths SHA verified on Mac installed client.
- Cloud 54.250 sec, Mac 14.770 sec. Both independently read all fixed dataset parts, latest natural-key selection including previous probes/revisions; 40 full-column date checks +40 observation-time as_of checks, zero mismatches. Six common report keys identical. Full known daily13+adj3 fields preserved.
- Evidence `/tmp/tushare-rrg40-fixed-ca7c-common-verified.json`. Exact helper/report SHA:
  - `/tmp/verify_tushare_rrg40_fixed_ca7c.py`: `11dc82748127b7f0691fcbf62704da179275cc63571803b02387fa0f70ff621f`
  - `/tmp/verify_tushare_rrg40_fixed_ca7c_mac.py`: `21a49fc33919133186a86c1494e5dd09e93ded8f752b13d7a1b8ade3f0c5627d`
  - `/tmp/tushare-rrg40-fixed-ca7c-cloud-verified.json`: `8890b805cbcba223869c33fbc2be0ce1acca613da0e85db08c64a0a0e9de9def`
  - `/tmp/tushare-rrg40-fixed-ca7c-mac-verified.json`: `fe752e4cdbe51dd97e5f1ad50827767c4e17b98bb5b5948a22cdd338014c916d`
- Re-run Mac: `/tmp/quantmind-calendar-factor-test310/bin/python /tmp/verify_tushare_rrg40_fixed_ca7c_mac.py > /tmp/new-report.json`; fixed immutable root only, socket/DNS/SQLite/provider-secret denied. Cloud stdin helper requires existing business entry; root deployment window ongoing, do not rerun cloud now.
- Scope remains these 40 dates/API tasks for diffusion window; as_of is system observation time, not supplier PIT. No claim of full RRG 2021–2026 history/calendar/member PIT/ETF mapping readiness.
