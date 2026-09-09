# Physical storage review ready

Structured agent; no runtime file changes/claims. Continuation of 20260909T003323Z-mac-storage-readonly-start-structured.md. Parent current baseline100e4df.

Cloud shallow stat 00:33:23Z took1.97s: audited regular files28.161GiB. Unique release+archive10.454GiB (not double-counted logical13.59GiB), documents indexes7.034GiB, objects6.353GiB, Parquet1.987GiB, attachments0.864GiB. Metadata including observation envelopes17.683GiB/62.8%. Directory/external snapshot accounting excluded.

00:36:15Z mapping-only follow-up:164 old release/archive pairs differ inode, same size, archive nlink1; potential3,895,267,328B=3.628GiB to reclaim after SHA verification.59 current pairs already share inode. Existing100e4df link_manifest_alias independently tested: preserves existing independent target inode by design.

Next candidate, not implemented: explicit opt-in existing alias replacement using safe dir-fd/O_NOFOLLOW and both SHA/size/stable identities, verified temporary hardlink then atomic os.replace+directory fsync under existing.archive.lock. Default preserve behavior unchanged; bounded maintenance, EXDEV skip, no new schema or deleted historical paths. Require corruption/race/crash/idempotence/reader tests.

Mac CURRENT e1386fc1... verified; three fixed manifests SHA checked.159809/159835 old descriptors reused unchanged, no deleted/changed metadata. Intervals added8 raw+8 observations+8 Parquet+1schema, then only prior archive reference plus planning/status changes; each still generated a distinct66.45/66.54MB manifest. These include validation/planning releases, not representative normal throughput. New66.69MB every120s would be44.72GiB/day if unchanged; estimate, not actual daily measurement. One-time inode dedup does not solve that growth. No schema/format change now; future cadence optimization needs explicit freshness/forced-final-publication contract.

Evidence/re-run scripts listed in /tmp/tushare-storage-review-20260909.json. No API calls, production writes, data deletion, worker control or runtime commit.
