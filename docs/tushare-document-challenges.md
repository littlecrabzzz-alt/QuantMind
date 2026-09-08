# Original-document script challenges

The downloader recognizes one narrow, observed JavaScript cookie/reload challenge
when a PDF is expected. A complete body up to 16 KiB must have a `<script>` wrapper
and all observed cookie/reload markers. Detection is static; the code never
executes JavaScript, calculates cookies, follows script reloads or changes browser
identity. Larger/different challenge templates retain existing mismatch handling.

A matched HTTP200 response gets `status=source_challenge`,
`content_kind=script_challenge`, `challenge_kind=javascript_cookie_reload`, and
`validation_status=unexpected_content`. The complete original remains an immutable
`attachments/<sha256>.bin` with its headers and byte count. `raw_complete` means
complete transfer, not a downloaded PDF. Parsing is not attempted. Existing HTTP
error and content-encoding statuses take precedence.

`source_challenge` uses the existing document-scoped terminal `blocked` state on
that attempt instead of consuming the remaining ordinary mismatch retries. The
original reference, attempt and evidence remain in inventory/index publication;
no task or historical evidence is deleted. Restarting or registering the same
observation/reference does not retry the blocked job. Other documents continue.
No host-wide block, retry loop, automatic access workaround or schema migration
is introduced.

This does not retrofit existing blocked/failed observations, and the current
reuse rule still excludes all blocked jobs: a distinct new observation can create
another job under existing semantics. A future negative-cache/manual-release
policy would need explicit review and must preserve revision evidence. The
candidate makes no claim to eliminate every future challenge download.

## Bounded 2026-09-09 evidence

Two retained `pdf.dfcfw.com` HTTP200/application-pdf responses were copied by the
parent from existing authority storage, not fetched again upstream. Both are 989
bytes, have no PDF header or EOF marker, and contain the same script template
apart from numeric literals. Their SHA256 values are:

- `2b2667e20f4bc6c6c219427e889bf849bbc3bb7254ca792685fc110bb2eb7c45`
- `967ddf4ac6df0c97e483271dfb3f51dcdd49bcb7a364d0eae24f9fdeae367679`

Local evidence: `/tmp/quantmind-document-error-diagnostic/<sha>.bin`.
Both were passed through the candidate fetch path using a simulated response and
connection, with no script execution. The status is now `source_challenge` and
the saved byte/hash inventory is unchanged. Committed tests use an inert comment
fixture containing the observed markers, not executable supplier challenge code.
They verify classification, narrow matching, immutable preservation, HTTP/encoding
precedence, durable blocking/idempotence, index inclusion and unrelated-job progress.

The retained `static.cninfo.com.cn` timeout samples contain no complete body or
HTTP status. Their DNS/connect/TLS/header/body failure stage remains unknown;
this candidate neither reclassifies them as challenges nor changes their timeout.
Original-document coverage stays incomplete for every blocked/timed-out reference.
Supplier-supported access or delivery guidance is a separate follow-up; purchased
Tushare data permission does not by itself explain the third-party host challenge.
