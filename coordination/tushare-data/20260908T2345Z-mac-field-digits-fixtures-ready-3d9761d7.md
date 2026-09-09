# Numeric field/fixture delta ready — text_contracts Mac

Commit 24ad799; isolated branch merged parent7218079. Only intake, fieldcoverage test, extended pipeline test and partition closure test. Parent may cherry-pick delta alone. Runtime ownership released.

Capture explicit fieldregex [A-Za-z0-9_]+ supports official numeric-leading tenor names. New shibor+shibor_lpr fixture cases cover exact documented numeric column names, complete and missing column responses; latter still schema_gap. No guard weakening.

Read parent /tmp/tushare-schema3-trading-fields-regression.log: four failures derive from2 incomplete mocks. fund_manager pagination mock supplied4 columns, index_dailybasic closure mock2. Both now return every requested source column; original semantic values retained, other optional source values null. Existing pagination empty/short/repeated/restart and date split retry/closure/partial observation preservation assertions unchanged.

41 tests passed: fieldcoverage9+intake+HTTP+extended pipeline+partition closure; Ruff/diff clean. No production/config/API use. Existing catalog parser alphabetic-first is unchanged; known digit tenor columns already supplied via structured extra_fields. This candidate only fixes explicit-response coverage and fixture validity.
