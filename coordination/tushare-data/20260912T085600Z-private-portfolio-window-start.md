# Tushare account-private portfolio production window start

- Fixed release `data-df2dceada681d30b2d4c24c7df5877452c5d27f2479557b493378d7f4ec3f7ff` and its Mac mirror are closed before this window.
- The normal Tushare Beat was stopped after publication. One already queued acquisition task remained, so the dedicated Tushare worker received a 360-second warm shutdown and is allowed to finish that task before exit.
- The main service, document worker, database and QuantDB remain outside the stop scope.
- The reviewed one-shot runner backs up the authority config, enables only `p_list` and `p_get` for one UTC snapshot epoch, runs one list call and at most 30 derived member calls at 30 rpm, and restores the original config bytes in `finally`.
- Private values remain in the authority database, raw objects, observations, Parquet and private create-only manifests/receipts. Coordination and Git record only counts, states and hashes.
