# Publish timing read-only review ready

Owner: structured agent. Scope: read-only bbe2f9e production completed status and local code review; no runtime files claimed/modified. Parent retains pipeline concept wiring.

Both existing tushare workers observed Up/healthy at 00:20:16Z. Completed 00:19:50Z and 00:21:49Z batches: 335 requests each; total 119.694/118.729s; publish 15.082/15.209s. Largest publish stage coverage_and_closure 4.482/4.482s, attempts+stat 2.679/2.435s, retain_previous 2.221/2.243s; document_index 1.025/1.100s. No failed stages.

Minimum next candidate: versioned expression index on jobs(json_extract(job,'$.api_name'),state), keeping current SQL output and scheduling. Existing epoch-leading index does not order API/state aggregation. Actual stage combines multiple operations, so cannot claim the full 4.48s is removable. Require migration rollback/idempotence, ordered coverage/scope equality, pending fairness and write-overhead regression. No candidate code prepared because parent owns pipeline wiring.

Fixed 120s beat + 90s acquire means reduced publish alone does not increase requests in already-under-120s batches. Two samples are not sustained throughput evidence. No API acquisition or worker control.

Evidence: /tmp/tushare-publish-live-timing-review.json; samples /tmp/tushare-publish-live-timing-samples.json; bounded read-only rerun python3 /tmp/read_tushare_publish_timing.py.
