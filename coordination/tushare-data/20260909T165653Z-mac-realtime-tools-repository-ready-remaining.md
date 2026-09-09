# Realtime10 仓库工具候选已提交
- Mac remaining_markets；独立 base eed2c88，branch codex/tushare-realtime-probe-tools，commit bc706de95a5c24521de181bb38bc9ca258c44465，已push且worktree clean。
- 仅4新增文件：scripts/tushare_realtime_probe.py、scripts/verify_tushare_realtime_fixed.py、scripts/test_tushare_realtime_tools.py、docs/tushare-realtime-probe.md。未改core/config/queue/ledger/生产。
- 从已审 /tmp realtime10 搬入，去除机器路径/手工helperSHA入参；默认dry-run、不生成slot；显式执行才取共享pipeline.lock、生成当日slot。15/120硬限；共享tiered_v1 resolved_api_rate、rollout账户较小值、已观察quota与持久request_gates；明确local quota 0HTTP继续保持prepared。结果白名单排除token/response body/header/上游message；105列和未知值在原文与固定Parquet审计保留。
- 验证：Python3.10专项24 tests通过，Ruff与diff check通过，两个CLI --help无token。日志 /tmp/realtime-tools-repository-final310.log。相关61tests中60通过，唯一旧失败 test_tushare_rate_policy.DurableQuota.test_guard_preserves_jobs_observed_gate_and_other_api_consumes 在未改主树单跑同样失败（/tmp/realtime-tools-base-existing-failure.log）；其quota fixture固定9月9日但Pipeline用当前9月10日，疑似跨日retry_at已过期。未改旧测试或掩盖失败。
- 交接：父只需pick bc706de；命令与真实固定seed前提见 docs/tushare-realtime-probe.md。未执行源探测、未读token/生产DB、未启用/发布/重启；权限与全历史/其他频率/PIT缺口仍在，无自动enable。
