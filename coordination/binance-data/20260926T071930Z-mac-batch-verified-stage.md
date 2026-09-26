# 币安批量补录：现货阶段已发布本机独立版本
- 节点：Mac local-sandbox；候选 worktree `codex/binance-data-20260926`，基线 afc8ef80，尚有未提交改动。
- 已完成：10个加密现货29,142行，4个bStocks332行；均至2026-09-25，质量检查缺日/重复/未闭合为0。新根 `.local-dev/project/data/binance-batch-20260926/{crypto-spot,tokenized-equity}`，原日更池不改。
- 独立复核：旧云端BTC/ETH与AAPLB payload哈希、原始经济值、Qlib/H5绑定通过；本机旧BTC/ETH存在旧解析1–2 ULP差异，未伪称双端版本相同，旧版保留。报告在 `output/binance-batch-20260926/`。
- 进行中：新池Qlib/H5实际消费、独立原始值复核，以及股票永续archive-only入口/边界测试。UNITREE09-25官方归档404，09-24归档可读，明确保存缺口。
- 后续：完整候选验证后只做新batch目录的增量云端发布，校验全部传输文件后暴露数据根；不替换 `/data/quantbc`，不启用策略/调度/交易，不占用共享服务重启窗口。
