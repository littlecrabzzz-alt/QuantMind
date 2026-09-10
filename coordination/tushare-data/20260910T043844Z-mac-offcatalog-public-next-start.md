# Tushare off-catalog public read-only batch start

- Branch `codex/tushare-catalog-discovery-next`, base `01265aa70bdc67e0e434304a06a441405a21a848`.
- Inputs: current official `waditu/tushare-data` reference commit `b68d5517e0cbe84d61774de26ad366d900c7eb92`, current official SDK commit `093856995af0811d3ebbe8c179b8febf4ae706f0`, and public official document bodies only. No token or data API call.
- Current-document candidates selected: `film_record`, `teleplay_record`, `bo_monthly`, `bo_weekly`, `bo_daily`, `bo_cinema`, `fund_sales_ratio`, `fund_sales_vol`. All stay default-disabled and permission-unverified.
- Non-blocking gaps: `ggt_top10`, `ggt_monthly`, `hk_hold`, `dc_concept_cons` still lack current complete documents. Current realtime and TMT pages will remain explicitly discovered for a later isolated batch if not implemented here.
- Parent-owned files excluded: `scripts/tushare_legacy_connect_probe.py` and its tests.
