# Bounded throughput review ready

Structured agent; read-only production existing status/logs/config and60 document attempts, no runtime files claimed. Parent deploying/integrating interval/DC separately.

00:56:29Z/00:58:37Z normal batches:327/337requests, acquire90.54/90.18s, total133.54/128.34s, publish26.25/23.58s. Active217-224req/min under shared240/min; whole-task147-158/min. Routine publishing now contributes to exceeding120s cadence; interval reduction not yet measured. Two samples cannot prove sustained improvement.

Independent hk_daily quota5/day remains (configured3605s lower floor cannot override observed17280s spacing/day cooldown); several50/min contracts independently gated. Additional API workers cannot bypass pipeline.lock/sharedquota. RRG3 versus16other enabledfamily weights1 =>15.8% preferred turns when all ready; optional6 yields27.3% share while allothers retained, not increased total quota.

Document worker remains2downloads/1parser,100phase operations/90s; latest16/22downloads plus10/18parse operations. Last60attempts:36downloads of which24success,7timeout,3mismatch,2challenge;24parse success. Distinguish phase operations from completed documents. Queue totals are growing scope, not complete remaining-history estimate.

Evidence and quantitative limitations: /tmp/tushare-throughput-review-20260909T0059.json. Recommended parallel work: interval integration/real gray verification, concrete RRG slice priority/validation, independent attachment-source evidence/failure diagnosis; no claim of linear worker speedup. No API calls, writes, queue changes or new config.
