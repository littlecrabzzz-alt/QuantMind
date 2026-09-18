# Mac Tushare batch-800 gray production result

- Time/node/task: 2026-09-18 01:37 UTC, Mac archive owner, Tushare full-local acquisition.
- State: production gray result accepted for continued observation; full historical acquisition remains in progress.
- Code: Mac/origin/cloud `master` was aligned at `fc9df65477f16fff0ba009fab406503286624360` before this record. This change records runtime evidence only.
- Scope: this task owns only this new coordination record and the private Mac acquisition configuration. Existing RRG/research changes and other untracked records remain untouched.
- Continues: `20260917T222124Z-mac-acquisition-pipeline-production.md` and `20260918T012143Z-cloud-acquisition-pipeline-handoff.md`.

The Mac private configuration raised only `batch_requests` from 700 to 800. The configuration SHA-256 is `842dc19cf414db70e828f42daf47b44b4e32d8ed160129fcc2756e3c849e578c`; the account and rollout ceilings remain 500 requests/minute, API-specific gates and daily quotas remain enabled, and production still uses one HTTP worker. The configuration change caused one automatic `planning_only` queue-reconciliation cycle before acquisition resumed. That phase did not call Tushare and was not a dry-run of the archive.

Four subsequent completed cycles performed 698, 334, 483, and 690 real Tushare requests. Their result counts were respectively `360/315/23`, `187/137/10`, `266/203/14`, and `377/292/21` for `sample_ok/empty_unverified/possibly_truncated`. All four had zero `rate_limited` results and no failed stage. The two low-throughput cycles coincided with broad supplier/network latency: request mean latency rose from 0.081 seconds in the first cycle to 0.265 and 0.175 seconds, with several APIs taking 1-3.7 seconds. The fourth cycle recovered to 690 requests in 102.166 seconds. Local result processing, durable gate reservations, and document workers remained healthy.

The 800 value is retained as a safe batch ceiling, not claimed as 800-request achieved throughput. The durable account gate still controls actual request timing, so the larger ceiling can use faster supplier periods without weakening the 500 requests/minute limit. At this checkpoint the archive reported `done=271494`, `pending=2883838`, about 2.489 TB free, an active Interactive LaunchAgent, and a zero-byte worker stderr log. Full acquisition continues on the Mac; the cloud remains a research-cache reader and must not start a full Tushare writer.

Next: continue observing completed cycles and supplier latency while the archive runs. Revert the private ceiling to 700 only if later evidence shows a repeatable regression caused by local scheduling rather than supplier latency. No service restart or cloud data-writer deployment is required for this documentation-only Git handoff.
