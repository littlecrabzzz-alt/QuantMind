# API HTTP failure evidence
- structured_contracts isolated worktree; based8249f6c. Own only tushare_intake.capture_sample and new scripts/test_tushare_http_evidence.py. Parent owns records/reader compatibility and deployment.
- Complete HTTP error body retained in existing immutable raw objects+observations after defensive Token redaction. HTTP429 rate_limited, other HTTP errors transport_error, never parsed as a successful dataset. Network/read interruption remains no complete raw. No production requests.
- Alert sent to parent: objects named .json can contain nonJSON HTTP body just as previous invalid_response bodies; records/read_samples must not blindly decode those into data. Mirror/checksum format unchanged.
