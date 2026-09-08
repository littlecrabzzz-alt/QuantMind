# Attachment failure evidence
- Owner structured_contracts, Mac isolated codex/tushare-structured; merged b199eab (88cc03d local merge baseline).
- Own only backend/shared/tushare_documents.py and new scripts/test_tushare_document_evidence.py; parent owns deployment/pipeline.
- Preserve complete bounded unexpected responses as immutable attachments/<sha>.bin with bounded diagnostic headers, content classification, completeness marker. Existing failed statuses/retries retained. Never parse as valid PDF/正文; encoded bytes remain encoded. Partial/timeout never complete. Reuse existing index/mirror files inventories; no new service or requeue.
- Temporary mock-only tests; no production access. Continues parallel-speed-deployed 20260908T194119Z record.
