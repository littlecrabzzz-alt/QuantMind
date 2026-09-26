# 币安首期数据验收（2026-09-26）

本次完成本地数据侧四步：历史采集、UTC/原生字段规范、质量与增量、固定版本研究读取。研究读取只涉及数据与因子计算，不代表策略回测、盈利能力或实盘链路已验收。

| 数据集 | 覆盖 | 已发布行数 | 消费结果 |
| --- | --- | ---: | --- |
| BTCUSDT 加密现货 | 2017-08-17～2026-09-25 | 3,327 | Qlib/H5 与 RD 固定数据入口通过 |
| ETHUSDT 加密现货 | 2017-08-17～2026-09-25 | 3,327 | Qlib/H5 与 RD 固定数据入口通过 |
| AAPLBUSDT 苹果代币化证券 | 2026-07-29～2026-09-25 | 59 | QuantBC 全量读取通过，CryptoAdapter 按产品类型拒绝 |
| CXMTUSDT A 股相关永续 | 2026-08-18～2026-08-31 | 14 根归档样本 | 仅来源和格式验证；未发布为研究数据 |

加密现货发布版本为 `binance-20260926T031215207598Z-42a749f1ae`，manifest SHA-256 为 `35aa61a644a94d41bd7e416842a8bc624b942550871ab86a0ec1c765ebaf9238`。AAPLB 发布版本为 `binance-20260926T031232984445Z-cf1cf774f3`。两个目录各自拥有 CURRENT、原始响应和历史版本。

## 验证证据

- BTC/ETH 共 6,654 行，无日期缺口、重复或未收盘日线；逐 symbol 查询上游首根 K 线，确认当前公开接口历史覆盖。AAPLB 59 行同样通过。
- 真实增量重跑经济数据摘要一致、修订行情数为零；交易规则元数据变化生成独立新版本。历史来源差异与采集时间保留，未覆盖旧版本。
- BTC/ETH 的 2018-02-08 REST 收盘时间与官方月归档不同，经济数值完全相同；校验官方 CHECKSUM 后按归档修正，保留两条修订证据。
- 最终版真实无网络容器验收：H5 全部 6,654 行，原始文件前后哈希不变；Qlib 最近七天的 14 行收盘价、成交额和日收益率与 Parquet 一致；任务内保存完整 source_manifest。
- AAPLB 独立消费验收 23/23 项通过，10 个数值字段共 590 个单元格与发布 Parquet 精确一致；确认 US/AAPL 元数据，研究适配器拒绝混入 crypto_spot。
- 后端镜像限定套件 **77 passed**，包含源解析/重试、缺口/故障发布、历史回补与刷新、产品隔离、来源时间语义、Qlib 路径、日历及手动/调度入口合同。Mac 原生环境缺 PyTables 的项目由容器实测补足。
- 新增文件及其余修改文件 lint 通过；`qlib_data_builder.py` 的一处 E741、`alpha_agent.py` 的六处 pd 注解 F821 已核对为基线原有问题；本次没有新增这些诊断。`git diff --check` 通过。

## 数据位置与运行状态

本地根目录：`/Users/lizeyu/Documents/ChatGPT/投资/QuantMind/.local-dev/project/data/`。

- `quantbc/acceptance/final-research-report.json`：最终真实研究数据消费报告。
- `quantbc/derived/binance-20260926T031215207598Z-42a749f1ae/`：已构建 Qlib/H5。
- `quantbc/acceptance/final-task/`：验收任务固定输入副本。
- `binance-tokenized-equity/acceptance/product-report.json`：AAPLB 独立消费报告。
- 主工作树 `.local-dev/binance-product-evidence/`：官方 ZIP、CHECKSUM 与匿名接口核实证据；具体路径见产品核实文档。

验收容器中该数据根挂载/复制到 `/data/binance`，报告中的绝对路径为验收时的容器路径；所有 source_manifest 通过 release_id 和文件哈希固定版本，不依赖主工作树的可变输入。

本轮没有向云端发布数据、开启自动日更或启动策略研究/交易。候选实现保存在 `codex/binance-data-20260926` 独立 worktree；本地数据准备命令及后续增量命令见 [操作说明](binance-data-operations.md)。目前常驻服务的 `ENABLE_CRYPTO=false`，实盘开关保持关闭，因此不能将本地研究读取通过表述为云端页面已开放币安市场。

## 股票产品边界

币安存在美股直接交易、bStocks 代币化证券及股票永续，数据含义不同。AAPLB 不代表底层 AAPL 证券的复权行情；CXMT 是 A 股相关的永续合约，不是沪市现货。本机合约实时接口返回 451，因此本次只核验公开归档，没有声称持续更新已经打通。真实证券历史行情、公司行动、资金费、标记价和指数价仍需分别接入与验收，详见 [官方产品证据](binance-data-products.md)。
