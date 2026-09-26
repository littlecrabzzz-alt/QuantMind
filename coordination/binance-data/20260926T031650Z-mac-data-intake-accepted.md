# 币安首期本地数据验收完成

- 节点/范围：Mac sandbox；完成历史补采、UTC/原生字段、质量与增量、实际 Qlib/H5/RD 数据消费。未运行策略、回测、交易。
- 代码：`codex/binance-data-20260926` / `47d24e61480ea3dc1bf61cfd60dc37c1e87b4e37`，已 push；worktree `/Users/lizeyu/.codex/worktrees/quantmind-binance-data-20260926`，干净。候选基于现主分支 `7b5dcea5`，未修改相邻 QuantDB PG 修复。
- 接续：`20260926T025031Z-mac-data-intake-start.md`。源码未合入主工作树，未占用 QuantDB PG 任务的共享服务窗口，未重启常驻服务。
- BTC/ETH：`binance-20260926T031215207598Z-42a749f1ae`，各 3327 根日线，2017-08-17～2026-09-25，合计 6654。CURRENT manifest SHA-256 `35aa61a644a94d41bd7e416842a8bc624b942550871ab86a0ec1c765ebaf9238`。
- AAPLB：独立目录，`binance-20260926T031232984445Z-cf1cf774f3`，59 根，2026-07-29～2026-09-25；US/AAPL/tokenized_equity_spot。不得混入 crypto_spot。
- 质量：缺口/重复/未闭合均 0；源首根边界确认。2018-02-08 BTC/ETH REST close_time 与官方归档不同，在经济字段完全相同、CHECKSUM 验证后采用归档并保留差异。历史回填 PIT 未验证，manifest 明确 available_at 仅理论收盘下界。
- 增量：真实重跑行情摘要相同、0 行经济修订；标的交易规则元数据变化生成新版本，旧版本不变。失败/损坏/中断保留 CURRENT、全历史刷新、产品门禁均有测试。
- 验证：后端镜像限定套件 77 passed；真实 Qlib 最近 7 天 14 行的 close/amount/收益与 Parquet 比对通过，H5 6654 行，原始版本哈希不变。AAPLB 独立 23/23 检查通过、590 个数值单元格一致，CryptoAdapter 拒绝。最终派生数据已复制回沙盒并由本机 adapter 再确认 ready，报告版本等于 CURRENT。
- 产物：主工作树 `.local-dev/project/data/quantbc/acceptance/final-research-report.json`、`quantbc/acceptance/final-task/`、`quantbc/derived/<release>/`；`.local-dev/project/data/binance-tokenized-equity/acceptance/product-report.json`。官方股票归档样本在 `.local-dev/binance-product-evidence/`。
- 文档：候选 `docs/binance-data-acceptance-20260926.md`、`docs/binance-data-operations.md`、`docs/binance-data-products.md`；复跑脚本 `scripts/binance_data_acceptance.py`。
- 部署状态：本轮数据仅在 Mac 沙盒。常驻服务 ENABLE_CRYPTO=false、ENABLE_REAL_TRADING=false；未发布云端数据、未开启自动日更。后续主分支集成/云端发布需沿用共享服务窗口及 handoff，不能将本轮本地消费通过视为云端页面已开启。
- 股票限制：CXMTUSDT 仅 2026-08 官方归档 14 根样本；实时合约 fapi 返回 451 后停止。真实 A 股/美股证券与 bStocks/股票永续保持独立，不能把该样本称为完整股票研究输入。
