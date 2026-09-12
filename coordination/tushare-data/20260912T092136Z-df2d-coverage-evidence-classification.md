# Tushare df2d coverage evidence classification correction

- The fixed-release audit now classifies retained gap outcomes as well as API-level capability rows. It remains an offline read of immutable release `data-df2dceada681d30b2d4c24c7df5877452c5d27f2479557b493378d7f4ec3f7ff` and made no upstream call or authority write.
- The 50 registered and planned interfaces without a published dataset divide into 37 with `permission_denied` evidence, 11 with `api_error` evidence and two available interfaces with only retained empty responses. No interface is unclassified.
- The earlier 34/14/2 wording counted only direct capability rows and therefore hid three permission denials and eleven retained API errors inside a generic blocked bucket. It did not indicate missing raw observations or lost data.
- Existing raw-response reviews identify the eleven API errors as supplier code 40101 for `film_record`, `teleplay_record`, `bo_monthly`, `bo_weekly`, `bo_daily`, `bo_cinema`, `fund_sales_ratio`, `fund_sales_vol`, `tmt_twincome`, `tmt_twincomedetail` and `stk_account_old`. The fixed audit reports only `api_error`, because the immutable manifest does not embed the supplier code or message; exact reason remains in retained observations.
- The two available-empty interfaces are `stk_alert` with four empty observations and `stk_high_shock` with two. Availability and HTTP 200 do not constitute a dataset, complete history, event absence, revisions, or PIT evidence.
- Repeated capability probes are not admitted for the 48 permission/error interfaces. `stk_alert` has at most one defensible new narrow range-filter probe; `stk_high_shock` needs a new authoritative nonempty date/code seed before another exact request.

The updated report is `docs/tushare-df2d-coverage-audit-20260912.json`, schema version 2, SHA-256 `bf20745992cfa78c426aa400032ae37f54f3f199596d259b91ac6a63d5c4d3b9`.
