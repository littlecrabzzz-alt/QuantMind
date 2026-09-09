# 相邻实时回放 2 API 纯候选 ready

- Mac remaining_markets；基线2233d3d realtime8纯合同；branch codex/tushare-realtime-replay，唯一增量745286347e92aa8b4845160dadcf286345c02635已push。独立worktree /Users/lizeyu/.codex/worktrees/quantmind-tushare-realtime-replay clean。只新增contract/test/doc3文件，未改registry/pipeline/store/mirror/配置、未生产调用。
- rt_idx_min_daily420、rt_fut_min_daily340是独立命名API，共18已知列全请求，defaultN无披露；共享官方输出表依据与SHA见docs/tushare-realtime-replay-intake.md，daily字段等价/权益/cap仍unprobed。独立积分权限不可由10100推断，普通兄弟接口cap/rpm不直接继承。
- group realtime_replay；默认off+当前显式UTCepoch；5精确大写freq，实际index/合约发现每次单代码，IDX:/FUT:源隔离。指数只当日无date输入；期货默认省略date_str由供应商定义当日。显式previous scope须同epoch、按合约真实端点回溯+上一交易日双验证窗口，准确ISO date_str；旧/缺失/夜盘日期不一致只阻前日，仍保留当前请求。不能today-1推日期、不能一般历史回填；纯helper不认证外部观察真实性，runtime必须认证来源。
- Python3.10新7tests+基线realtime8的12tests全部通过(0.003s/0.019s)，禁socket/DNS；Ruff/format/diffcheck通过。测试节假日是合成关系，不是实际交易日或权益证明。权限、隐藏未知列、无PIT、单码饱和、会话日期和历史scope义务继续保留。
