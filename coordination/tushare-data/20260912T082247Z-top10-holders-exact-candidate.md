# top10_holders + top10_floatholders 精确批次候选

独立候选已在 worktree `/private/tmp/quantmind-top10-holders-exact` 完成，分支 `codex/top10-holders-exact`，基线 `9fe4c38773b2710367ed25a532fdfe33fa83ca1e`，候选提交 `df542c79de77f54745b2ccf795697639f4c1a0dc`。未 push、未部署、未读取凭据、未访问上游、未读写生产 authority。

候选新增：

- `scripts/prepare_tushare_top10_holders_batch.py`，SHA-256 `599bba5681c15a7697f93f3849ebaf9741c12d82cb9729d3f91586e132d497c6`
- `scripts/run_tushare_top10_holders_batch.py`，SHA-256 `feeecc30d113855a03df5c90b077ccbb62b90562609fb1269166368787f38c49`
- `scripts/test_tushare_top10_holders_batch.py`，SHA-256 `9e7174e5f7313bc271bb8ce7a87c7fb587b21d475925f30a29267906e7e1fbff`

批次合同：

- 每个选中单元必须是 `top10_holders` 与 `top10_floatholders` 的完整 sibling pair，共用同一 `epoch + ts_code + start_date + end_date`。
- 只接受法定日期、非逆序的有界报告期区间；股票代码限定为沪深北 supplier code。
- 按最新区间和沪/深/北轮询选择，最多 180 pair / 360 任务。
- 任务必须为 `pending`、`tries=0`、`result IS NULL`、`attempts=0`；全 epoch 存在同 logical job 的 peer 时整个 logical request 排除。指定的历史 manifest 中已冻结 task/logical request 也排除。
- manifest 固定 release ID/manifest SHA/CURRENT pointer SHA、authority config SHA、相关 code SHA、task IDs SHA、logical request SHA 和 pair inventory SHA。
- plan-only 仅校验 manifest 与本地代码，显式抦截网络与 secret，不访问 authority，不写入，不发布。
- execute 需要显式传入全部 pin，使用已存在的非阻塞独占 `pipeline.lock`，锁内重验 CURRENT/config/code/task identity/pristine/attempts，仅把固定 task IDs 传给 `Pipeline.run`，请求限额必须等于 manifest 任务数且不超过 360，硬时限不超过 90 秒，不规划普通队列，不发布。

验证：

- `ruff check` 三个新文件：通过。
- `py_compile` 三个新文件：通过。
- `PYTHONPATH=scripts python3 -W error::ResourceWarning -m unittest scripts.test_tushare_top10_holders_batch scripts.test_tushare_financial_pit_batch`：21 项通过。
- preparer/runner CLI `--help`：通过。

生产冻结阻塞：本子任务不允许读取生产 authority，因此尚未产生真实 360 任务 manifest。Root 需在 writer 自然排空时提供：当前 release ID/manifest SHA、目标 epoch（预计 `history`）、所有既有 top10 exact manifest 路径，并让 preparer 在非阻塞共享锁下生成 authority 外的新 manifest。然后先跑 plan-only，复核 180 个完整 pair、CURRENT/config/code/task/logical hashes 后才可执行。

范围限制：本批次仅补有界报告期区间的已规划叶任务。不界定 stock-only 任务、未知历史起点、旧报告迟发修订和 PIT 完整性仍然是独立覆盖缺口。
