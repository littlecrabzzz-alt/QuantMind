# Tushare account-private portfolio production window complete

- The first invocation failed during local repository-path setup before config, credential, database or upstream access. The outer recovery hook restarted both services and the authority config remained byte-identical. Commit `0f1fc533` adds the explicit container repository path and passed an import-only check before retry.
- The accepted snapshot epoch is `20260912T090427Z`. The exact list stage made one upstream call at 30 rpm and retained a successful HTTP 200 empty observation. The exact member stage therefore contained zero tasks and made zero upstream calls.
- The private summary is 4,332 bytes, mode 0600, SHA-256 `c738d631bd5f496e074cbc03a24e93ed29526ad1754d5517604a68d95642fff6`. Manifests, receipts and any private values remain under the authority `private-portfolio-batches/` directory, mode 0700; none were copied to Git.
- The production config was restored byte-for-byte to SHA-256 `8ea3f3c5331130058dc854ded3a53d2051c78bb352a2a14e209ff43373cfae8a`; portfolio reads are again default-disabled. No release was published and `CURRENT` did not change.
- Normal Tushare worker and Beat were restarted. Main service, worker, document worker, Beat and `quantmind-db` are healthy with restart count zero and no OOM. QuantDB was never stopped.
- Safe machine evidence: `docs/tushare-private-portfolio-20260912.evidence.json`.

The empty response proves only this account and snapshot observation. It does not establish historical absence, deleted or intermediate portfolios, future snapshots, atomic list/member timing or list saturation semantics.
