# Fixed research_report filename comparison complete

text_contracts / Mac / read-only. No upstream/credentials/production writes or runtime edits. Source mirror CURRENT and mirror-status matched statusverified at selection. Pinned release data-05a74924173402344b86b4bd515828aacd7b373c9d6d969673025c97b8290f03; manifestSHA05a74924173402344b86b4bd515828aacd7b373c9d6d969673025c97b8290f03 independently verified.

Bound: read only94 research_report Parquet footers referenced by this manifest to select date diversity, then exactly10 distinct requests. No raw-directory scan. Selected10 Parquets,10 observationJSON and10 referenced rawJSON individually passed bytes+SHA against immutable manifest; raw objectSHA also equals observation reference. Total verified selected bytes31386412. Only schemas/dates/counts analyzed; no report正文 exported. Observations and all source files remain unchanged.

All10 requests use start_date/end_date and the identical explicit11-field list: abstr,author,file_name,ind_name,inst_csname,name,report_type,title,trade_date,ts_code,url. All10 raw schemas return exactly the other10 fields and omitfile_name. Total6033 retainedrows. There is no field-name/request spelling variation in this sample.

| Requested range | Rows | has_more | Observation |
| --- | ---: | --- | --- |
| 20260908..20260908 | 104 | false | 2be418241f754316bc5da714eabe0862.json |
| 20260907..20260907 | 101 | false | 7bfd334fe51d404e801633f9dd5aa19e.json |
| 20260906..20260906 | 82 | false | a59391650a694840a72bb1dbbd556e9c.json |
| 20260905..20260905 | 14 | false | ae92b3cc00f74338bc5aa71843bcf684.json |
| 20260801..20260816 | 854 | false | b785c760b9ba469fa1a251a97b9730bb.json |
| 20260701..20260716 | 878 | false | 39b20ee537134aa59e428e8b08b31f6a.json |
| 20260101..20260131 | 1000 | true | c8f0756b1ad5494ea9d2a7ede29aa2c5.json |
| 20230101..20230131 | 1000 | true | 50d98789d9e94ee3a8a7131ecc1073fa.json |
| 20221101..20221130 | 1000 | true | 6a26fdb520984641aa6bb9047cb6b505.json |
| 20221001..20221031 | 1000 | true | b0750473814b4996bca4a7572f591e43.json |

## What this establishes

- Four recent one-day ranges and two half-month ranges return14..878rows/has_more=false and still omitfile_name. Therefore observed omission is not limited to October2022, old data, full1000-row pages or multiday windows.
- January2026 month request also omitsfile_name; its actual response includes records whose trade_date is20260121, the date shown in the official415example. This weakens a simple “only that date/new period has filename” explanation.
- All selected requests use ranges, including start=end for single days. No exact trade_date=20260121 request was selected/verified. A difference between explicit trade_date parameter and date ranges, or an outdated/incorrect official example, remains unresolved. No controlled account probe was added and no general unsupported/permission conclusion is warranted.
- Six below-cap results predate the guard and preserve recorded status sample_ok/field_coverage absent. The derived field gap is a new read-only finding, not a mutation of those old assessments. The October2022 result has the newguard gap and possibly_truncated; all four1000-row responses have supplier_has_more=true and still need their independent row-coverage closure.

Minimum next step remains retainfile_name+known_field_gaps, preserve all10 source columns and attachment URLs, and ask supplier/inspect already-retained exact trade_date-mode evidence if it becomes available. Do not synthesizefile_name from title/url, erase known gaps, or silently remove the requested field.

Full request/fields/date/has_more/observation/object/Parquet hashes: /tmp/quantmind-research-fixed-field-comparison-20260909.json (SHA256 70982776609a4b685bc3cad017e3190b48f806642de9c0d80240120225824c4b). Script /tmp/quantmind-research-schema-compare.py; metadata-only selection evidence /tmp/quantmind-research-schema-candidates.json. Original mirror root /Users/lizeyu/Library/Application Support/QuantMind/tushare. Current result supersedes earlier “only one2022response is confirmed” scope in20260908T234238Z-mac-research-filename-review-ready-a447d334.md; original official415ambiguity unchanged.

Review complete; no runtime ownership or codecommit.
