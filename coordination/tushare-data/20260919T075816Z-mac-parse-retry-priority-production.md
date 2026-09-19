# Mac parse retry priority production verification

Commit `f435a48d` was merged and pushed to `master`. The existing archive
worker first reached a natural disabled boundary with no active download or
parse child; the runtime was then reinstalled and reactivated without
interrupting an archive transaction. The new LaunchAgent PID is 54716 and the
deployed `tushare_documents.py` SHA-256 matches the repository at
`33e1b3086c6756365201a0a9c24609102e0dcc58cd0ba87ae1f00a8f8a80faef`.

The first production document phase upgraded claim metadata from v5 to v6 and
created both exact indexes. Before that phase, 107 downloaded PDFs were still
eligible `parse_failed/parser_process_failed` recoveries. During the first
cycle the count fell to 89, while total parse failures fell to 208 and parse
timeouts fell to 100. The cycle completed successfully at
2026-09-19T07:57:53.591295+00:00 with 786 acquisition requests and 76 document
stages. Lower document throughput is expected while large bounded retries have
priority; the normal queue remains durable and resumes after the finite retry
set settles.

The archive worker remains active with the 300 GiB reserve unchanged. No token,
order, or supplier credential was recorded.
