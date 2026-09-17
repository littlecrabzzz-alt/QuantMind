# Cloud Tushare fence after index period replacement

- Time: 2026-09-17T19:50:16Z
- Verified cloud code head: `9bcd23de536bc8716ba788afbeb7a26017ef8bdb`
- Dual-node source digest: `4ce9ce3cd377beaaa6cbe29ca92edbb7db9cef888d6f1668a8330594853215f3`

The dual-node handoff fast-forwarded `/root/code/QuantMind` while retaining synchronized working files. The cloud Tushare boundary was then checked directly:

- `tushare-research-cache.timer`: enabled and active.
- `tushare-research-cache.service`: inactive between timer invocations, as expected.
- Full archive writer unit: absent.
- `/root/data/disk/quantmind/project/data/tushare/ARCHIVE_RELOCATED.json`: `source_paused=true` and `owner_hostname=lzydeMBP.lan`.
- Mac archive worker: production acquisition remained active after the maintenance restart.

The cloud node therefore has the reviewed code and bounded research-cache reader schedule, while the Mac remains the only full Tushare archive writer.
