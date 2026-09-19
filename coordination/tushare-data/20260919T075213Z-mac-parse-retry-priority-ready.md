# Mac document parse retry priority candidate

Production observation found 107 downloaded PDFs still marked
`parse_failed/parser_process_failed` after the v5 CPU-limit recovery. All had
`parse_tries=0` and `parse_retry_after=0`, but the parse claim query applied
`ORDER BY id LIMIT` across both ordinary `parse_pending` rows and retries. More
than 100,000 ordinary parse rows could therefore keep higher-ID recovered
failures out of the candidate set.

The candidate advances the claim schema to v6 and adds exact partial indexes
for due parse retries and ordinary parse-pending rows. Claim selection reads
each bounded class independently, then preserves download-retry priority,
parse-retry priority, and ordinary work. Existing five-attempt limits,
cooldowns, resource guards, evidence, and download ordering are unchanged. The
v5-to-v6 migration only creates indexes and does not replay the earlier CPU
recovery mutation.

Validation: the nine document suites passed 104 tests; the focused parallel
suite passed 28 tests after the final assertion; Ruff, Python compilation, and
`git diff --check` passed. Existing Python 3.13 test-suite `ResourceWarning`
output remains unrelated. Production deployment is pending a natural
archive-worker cycle boundary.
