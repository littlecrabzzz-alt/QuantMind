# Tushare realtime/TMT bounded probe candidate ready
- 时间、节点、任务标识：2026-09-10，Mac，realtime-tmt-probe
- 状态：待交接
- 分支、worktree、提交：`codex/tushare-realtime-tmt-probe`；`/Users/lizeyu/.codex/worktrees/QuantMind-tushare-realtime-tmt-probe`；`64c9e89de4d9b1b89cc465f2a7a1df9f073fb5c1`（已 push，基线 `bec7e6aa`，ahead 1）
- 分工：新增 `scripts/tushare_realtime_tmt_probe.py`、离线测试与 `docs/tushare-realtime-tmt-probe.evidence.json`；未访问生产、Token、Tushare 数据接口，未改配置/启用状态/发布。
- 接续：`20260910T070051Z-mac-realtime-tmt-probe-start.md`。

候选覆盖 `rt_min`、`rt_etf_min`、`rt_etf_min_daily`、`tmt_twincome`、`tmt_twincomedetail`。计划为 5 个基础请求；仅两项 TMT 成功且存在合法原始行时各追加 1 个精确过滤请求，最大 7 次、120 秒、无重试。实时代码从既有固定发布种子验证器提取实际 stock/深圳 ETF；TMT 使用官方 item 8 / symbol 6156 示例，aggregate 30 个月、detail 1 个月，后续 date/item/symbol 仅从本次原始响应派生。执行固定 helper SHA `2f8ca6547fa097bd98b2fe860b72ae9b532d753d4ff125fe22c4744252965313`，并固定两个复用 helper 的 SHA；保留 authority/schema6/LOCK_NB/tiered_v1/account+API+observed quota gates/capture_sample raw+observation/脱敏报告合同。所有接口仍默认关闭，积分或同族结果不外推权限。

验证：
- `PYTHONPATH="$PWD:$PWD/scripts" /tmp/qm-tushare-next-py310.6QJFDY/bin/python -m unittest -v scripts.test_tushare_realtime_tmt_probe scripts.test_tushare_realtime_extra_contracts scripts.test_tushare_realtime_replay_contracts scripts.test_tushare_realtime_runtime scripts.test_tushare_offcatalog_contracts scripts.test_tushare_offcatalog_probe scripts.test_tushare_rate_policy scripts.test_tushare_pipeline`：87 passed。
- `PYTHONPATH="$PWD:$PWD/scripts" /tmp/qm-tushare-next-py310.6QJFDY/bin/python -m unittest -v scripts.test_tushare_realtime_tools scripts.test_tushare_intake`：30 passed。
- `uvx --from ruff==0.12.7 ruff check --select E4,E7,E9,F scripts/tushare_realtime_tmt_probe.py scripts/test_tushare_realtime_tmt_probe.py`、普通 Ruff、`ruff format --check`、JSON parse、`git diff --check`：通过。

父任务生产前先确认 `/data/tushare/validation/realtime-probe-20260910/seeds.json` 仍存在且 SHA 与原 probe 报告的 `seeds_sha256` 一致；不存在则记录“无法安全探测实时三项”，不要重建/猜代码。先 dry-run，再用全新 validation 报告路径执行：

```bash
seed=/data/tushare/validation/realtime-probe-20260910/seeds.json
seed_sha=$(sha256sum "$seed" | awk '{print $1}')
python3 scripts/tushare_realtime_tmt_probe.py --root /data/tushare --seeds "$seed" --seeds-sha256 "$seed_sha" --report /data/tushare/validation/realtime-tmt-probe-20260910/probe.json
python3 scripts/tushare_realtime_tmt_probe.py --root /data/tushare --seeds "$seed" --seeds-sha256 "$seed_sha" --report /data/tushare/validation/realtime-tmt-probe-20260910/probe.json --seconds 120 --execute --expected-helper-sha256 2f8ca6547fa097bd98b2fe860b72ae9b532d753d4ff125fe22c4744252965313
```

下一步：父任务合并候选，在云端只读核对旧 seed 文件/报告 hash 后执行；真实响应需另做固定验证和发布，不能由本探针自动启用。
