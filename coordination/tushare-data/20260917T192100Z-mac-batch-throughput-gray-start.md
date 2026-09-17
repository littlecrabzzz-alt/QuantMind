# Mac Tushare batch throughput gray start

- Owner: Mac native archive at `~/Library/Application Support/QuantMind/tushare`.
- Scope: raise only the bounded request count per 100-second acquisition cycle from 400 to 700. The account ceiling remains 500 requests/minute, the resulting batch ceiling is 420 requests/minute, and all API-specific gates and daily quotas remain authoritative.
- Safety: apply the node-local config atomically, retain a rollback to `batch_requests=400`, wait for the existing cycle boundary, and accept only after real provider cycles complete without rate-limit, transport, or pipeline failures.
- Evidence: write a credential-free receipt under the archive `validation/` directory. Do not put the Tushare token or other account secrets in Git or coordination records.
- Boundary: this is a production throughput gray change. It does not change the Mac-only full-archive authority, restart cloud acquisition, or claim historical completeness.
