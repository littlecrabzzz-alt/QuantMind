# Tushare fund NAV/share next exact wave

- Safe drain completed without revocation: Beat stopped, `tushare_acquire` consumer canceled, active task `4d0c4d61…` succeeded, worker stopped only after active became empty.
- fund_nav batch 6: 360 first-attempt requests in 46.823s; 217 done, 31 empty, 112 split_pending. Manifest `e657e14e57c55e0610f3fbfc209d24fc07398e55c77aada06a8cd20e0dfa3e69`; receipt `9ec3b31129be3e732a37a0b813bfb622ab4e9432ce06a740d265d645fea6d057`.
- fund_share batch 5: 360 first-attempt requests in 45.523s; 248 done, 112 empty. Manifest `ac7a797301125bba23ad4d99510643c39c0ff6fdb92fd46bc6f96fcad8798a9b`; receipt `cfb85916a177819a4a43ee09668fa107a1e4d45a9519edd9882aa1a2ae61ef8d`.
- Both batches preserved CURRENT and did not publish. Dedicated worker and Beat were restored; wait for the normal fixed-release cycle and Mac mirror before offline readback claims.
