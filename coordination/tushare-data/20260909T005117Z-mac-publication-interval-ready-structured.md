# Routine publication interval candidate ready

Structured candidate97c8934c47e56579b4c46074f62fe3cf3633fd67 on codex/tushare-publish-interval, based100e4df. Only tick small block, new scripts/test_tushare_publish_interval.py and docs/tushare-publication-interval.md. Everything outside tick in pipeline confirmed unchanged by source-prefix/AST comparison. No production configuration, scheduling, service or data writes. File ownership released for parent integration.

Config publish_interval_seconds nonnegative integer defaults0; default publishes each completed tick and does not write checkpoint. Enabled mode validates CURRENT, uses existing scheduler_state publish_success_at only after successful return (including noop), and forces publication check on clock rollback/missing pointer. Hand publish remains immediate and unchanged. Failure retains checkpoint and error propagation.

Status publication separates current_release_id, performed, pending, status and mirror_status=not_checked. Top-level counts remain acquired-state; deferred release_id remains old fixed view.900s is minimum interval, actual tick completion can make about16min or longer; independent Mac15min polling can add another cycle. Mutable intermediate planning/index snapshots coalesce; all raw/observation/attempt/document-version evidence survives.

Validation Python3.10:75 tests in3.365s, covering interval8 + publish timing + tick timing + extended pipeline + acceptance + archive + aliases + document buckets/index. Real MockTransport same job4 API responses/observations/Parquet and4 document original/text versions with8 download/parse attempts survive2 deferred ticks and reach fresh mirror verify_data without SQLite. Ruff passed, git diff --check passed. No throughput/storage reduction claimed as measured production result.

Re-run new tests: uv run --no-project --python 3.10 --with httpx --with pyarrow --with duckdb python scripts/test_tushare_publish_interval.py. Parent to combine DC candidate and validate default/900 behavior before explicitly enabling.
