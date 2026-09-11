# Fixed release eef6 closure for three exact batches

- The normal publisher completed as Celery `SUCCESS` in 189.313 seconds with zero upstream calls. It atomically published `data-eef6e8bac0e0e7aa10ab5b8d6893529cbfeec85b3568dc0184181d653b3508d0`; the 340194663-byte manifest contains 114858 datasets and 844934 files, and its computed SHA256 matches the release ID.
- Mac LaunchAgent run 203 downloaded 7728 incremental files, verified all 844934 manifest entries, emitted no stderr and atomically switched the fixed mirror to eef6.
- The persistent verifier positively checked the 2692 unique references from financial batch 20, index daily batch 9 and fund price batch 16. All 26546285 bytes are present with matching metadata and physical SHA256; missing, metadata-error and physical-error counts are zero.
- A production image read the fixed Mac mirror with network disabled, socket and DNS guards, empty Tushare token variables and a read-only mount. `index_daily`, `fund_daily`, `fund_adj`, `fund_share`, `income_vip`, `balancesheet_vip` and `cashflow_vip` each returned three rows; upstream calls remained zero.
- The first readback invocation omitted the repository backend mount and failed at import before any data or upstream access. The corrected invocation used the actual deployment mount contract and passed. This is retained as a non-blocking execution correction.
- API, Tushare Worker and Beat are healthy. The cloud volume has 219879940096 bytes free, leaving 112505757696 bytes above the 100 GiB hard reserve.

These three batches are now immutable and locally usable without Tushare Pro. Complete history, revisions, `known_at`, PIT membership, RRG tradability and PCF coverage remain open. Machine evidence: `docs/tushare-fixed-release-eef6-three-batches-20260911.evidence.json`.
