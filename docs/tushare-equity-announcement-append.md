# Tushare 全市场公告历史追加规划

生产 `equity_event` 历史流先展开逐股十大股东窗口，导致无需股票标识的 `stk_holdernumber`、`stk_holdertrade`、`repurchase` 月窗口长期排在后面。当前权威库中三个接口各只有 17 个任务，而 `history:equity_event` 仍在 offset 175500。

新增 `history:equity_announcements` 只复用现有三份合同并保留原 group、任务 identity、限频、重试、原文和发布路径。它不修改旧 `history:equity_event` 的 signature、offset 或任务；已存在 ID 由 SQLite 幂等跳过，而且不消耗每轮 500 个新任务的上限。按生产配置 `19900101` 到 2026-09-03 共 1323 个历史月窗口，其中已有 42 个，预计新增 1281 个。

部署不需要改生产配置：它受既有 `enable_equity_event` 和 `equity_event_apis` 共同门控。合并并完成双端核对后，等采集任务自然排空，只重启 `tushare-worker`。随后只读确认 `history:equity_announcements` 在有界轮次内到达 `done=1`，三个 API 的新增任务进入原 equity_event 消费组，再沿既有不可变发布和 Mac 镜像路径验收。

`19900101` 是请求范围，不是上游历史下界证明。单日饱和、修订、删除和历史可见时点继续保留 `coverage_unverified`/PIT 缺口；入队和下载都不能单独证明历史完整。详细只读证据见 [机器摘要](tushare-equity-announcement-append.evidence.json)。
