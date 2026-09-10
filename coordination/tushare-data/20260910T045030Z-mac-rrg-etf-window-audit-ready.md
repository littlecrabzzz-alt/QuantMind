# RRG ETF full-window fixed-release audit ready

- Branch: `codex/rrg-data-closure-next-2`
- Candidate: `968d8e43`
- Base at validation: `aff291928b50b363de433e8527d6b87a48f1f647`
- Fixed input: `data-03885aef45ce7be5ce812f4305734a7c8852646a09cfa567383215d10e5f6d22`, 2022-09-01 through 2026-09-01, upstream calls 0.
- Result: 6,740 CITIC member rows have 0 verified known_at rows; 1,027,679 lifecycle-session ETF pairs include 1,022,792 exact valid price+factor pairs and 4,887 missing price pairs; 51,055/51,278 observation-envelope monthly execution pairs have exact valid price+factor. No fill or return/trading calculation.
- Other coverage: 10 fund_div events across 4 codes but no empty receipts; etf_limit has 0 window code-days; PCF has 2 code-days and 0 monthly execution pairs.
- Plan: 3,655 review-only active candidates (1,888 price diagnostic ranges, 1,718 fund_div receipt jobs, 49 etf_limit month windows); 5,774 PCF code/year windows remain dormant until an authoritative PIT ETF-industry map exists.
- Evidence: `/tmp/quantmind-rrg-etf-window-audit-20260910T0445Z/report.json` SHA256 `74d6798cab10c1ead48eca23927a511bd7192c882c8855c20b1df8f4737e1fe6`; repository summary `docs/tushare-rrg-etf-window-audit.evidence.json`.
- Validation: 6 focused unittest cases pass; Ruff passes; JSON and diff checks pass.
- Remaining gates: authoritative CITIC known_at/revision evidence; historical ETF-industry mapping and historical-universe proof; ETF suspension/open-tradability source; per-code dividend terminal receipts; exact-day PCF publication/revision evidence.
