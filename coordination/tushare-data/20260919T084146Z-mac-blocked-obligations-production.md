# Mac Tushare blocked-obligation production acceptance

- Authority: Mac local archive
- Commit: `313f41e0`
- Deployment: native LaunchAgent runtime hashes match the repository
- Worker: `com.quantmind.tushare-archive` returned to `running`
- Safety: the worker drained at a natural cycle boundary before deployment; the
  300 GiB disk reserve and 500 GiB NAS warning remain enabled

The first completed production cycle after deployment reported:

- 800 acquisition requests
- 1,886 document stages
- 781 retained blocked jobs
- 0 unclassified blocked jobs
- `changes_job_state: false`

The 781 retained jobs are fully explained by durable evidence:

- 764 replaced parents retained for audit
- 11 supplier APIs reported unavailable
- 4 unsplittable source caps
- 2 retained rate-limit probes without entitlement evidence

Validation used the deployed runtime dependencies. The related 136-test suite,
17 focused worker/classification tests, Ruff, bytecode compilation, and Git diff
checks passed. A production read-only query returned the same 781/0 inventory.
No token, order information, or other credential is recorded here.
