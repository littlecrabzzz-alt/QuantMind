# Attachment body diagnosis ready — text_contracts / Mac

Scope: read-only retained original bodies/metadata; no runtime edits, production queue changes, new upstream calls, cookies or browser execution. Parent copied two already-existing authority .bin files into an isolated /tmp directory; reviewer independently verified bytes/SHA256. Original content treated only as untrusted text.

## Confirmed source response: script challenge, not PDF

Both 989-byte bodies begin `<script>` and end `</script>`. Static literal markers: `EO_Bot_Ssid`, `__tst_status`, `cookie`, `location.href`, `setTimeout`. No `%PDF-` or `%%EOF` anywhere. The two scripts match after replacing numeric literals; these are one challenge-page template with variable values. No script was executed, cookie calculated/used, or reload performed. This is evidence of a JavaScript cookie/reload challenge interstitial from the download response path, not an unsupported PDF structure, PDF encryption, HTML article, or a PDF parser failure. Do not identify a specific CDN vendor/IP policy/account cause from these markers alone.

| Attempt | Document ID | SHA256 / local .bin | Bytes |
| --- | --- | --- | ---: |
| 3455 | 00e8a9717d5fb039fe0884694f1f4645cfcff04a1e3df58fb4845366cd05074b | /tmp/quantmind-document-error-diagnostic/2b2667e20f4bc6c6c219427e889bf849bbc3bb7254ca792685fc110bb2eb7c45.bin | 989 |
| 3454 | 0030a6fa2aa10f21e14b387c0c1ffc35e53622df5bc81046ff59b03b655515ee | /tmp/quantmind-document-error-diagnostic/967ddf4ac6df0c97e483271dfb3f51dcdd49bcb7a364d0eae24f9fdeae367679.bin | 989 |

Authority counterparts are /data/tushare/attachments/<same sha>.bin, observed HTTP200/application-pdf/raw_complete=true/pdf_content_mismatch. `raw_complete` correctly means complete transfer, not valid original document. Existing parser correctly never runs on them. `content_kind=unknown` occurs because fetch_document's HTML probe recognizes html/head/body/div/p but not a script-only wrapper. The format classification is less specific than evidence now permits; this is not a reason to accept the body as PDF.

Representative metadata for additional attempts3461/3460/3459 is /tmp/tushare-throughput-attachment-examples.json (SHA256 de4aab65c0ffdec345bf84279b2b13d8c545e88832540724086fabc9a4128c60): sizes988/988/990, same HTTP/type/mismatch. Their raw bytes were not inspected, so do not generalize the two verified bodies to every one of37 mismatches or later31mismatches. Bounded aggregate source is /tmp/tushare-throughput-review-20260908T232305Z.json and earlier shared 20260908T232305Z-mac-throughput-parallel-ready-structured.md. Report stages are not independent full-backlog samples.

## cninfo timeout remains a specific open gap

Attempts3458/3456/3451, doc IDs00e9c0e56711d324ee654a67b409ebf85c183455fc432e4303ec6d03c87f046f /00e744cc7b653f97df3446370a1712975a9b10af6a4e6bccabc3d49814e6d0b8 /00ee02713e002acd486f6d62f0d33099a1f394f4b3ebf1c9a76080b591837760, all static.cninfo.com.cn: download_timeout, parse not_attempted, raw_complete=false, files=[]. There is no saved complete error body or HTTP status. `_download_job` emits this when the total child deadline expires (including DNS/connect/TLS/headers/body), with two-worker budget min20seconds and remaining outer batch time. Metadata does not prove which stage stalled or how much budget that attempt received. Do not claim HTTP403/429, bot protection, malformed URL, or format/parser fault. No blind increase of concurrency/timeout is justified by these samples alone.

## Minimal candidate options; none implemented here

1. For PDF-expected responses, add bounded static challenge classification using explicit observed markers + script wrapper. Persist failure detail such as script_challenge while keeping raw_complete, headers, original .bin/hash and validation_status=unexpected_content. Never execute JavaScript, create cookies, spoof browser state, drop original bytes or mark downloaded. Test the exact shape with small synthetic marker text, not runnable vendor challenge replay.
2. Existing pdf_content_mismatch has up to5 persistent retries. This predictable challenge class could become an explicit supplier-access gap/manual-review state instead of repeating the same ineffective request. Any such retry-policy change is a separate parent-approved candidate; do not bulk-delete/overwrite existing jobs/attempts. Ask data supplier for a supported authorized original-document delivery path or access guidance; independent Tushare research_report permission does not prove unrestricted access to its third-party PDF host. Successful metadata/other document work continues, while original PDF/text completeness stays false for these references.
3. For timeout diagnosis, first record total allocated budget/elapsed time and distinguish child-deadline from socket exceptions during already-scheduled attempts. Stage timings require additional child instrumentation and must preserve its hard bound; no need to trigger extra requests. Only then decide whether supported host behavior calls for a timeout or resolver handling fix. Report current cninfo original-content gap without blocking other hosts or metadata ingestion.

No changes to runtime or queue ownership; diagnosis complete and handed to parent. All retained originals remain immutable.
