# BTC/ETH 主动成交字段独立准入完成

固定源 `binance-20261010T001517685958Z-7c1f6c5ec7` 和既有 development.jsonl 的 2017-08-18～2026-03-24 开发段：3141 UTC 日期、6282 行，两币共同键完整；成交字段有限非负、分母非零、主动买严格不超过总量、amount=quote_volume、时间/来源/冻结面板一致。3141 开发分区哈希全部匹配固定 manifest。两份既有 2018-02 月 ZIP 的哈希、receipt、供应商 CHECKSUM 及 56 行成交字段独立吻合；未打开其余原始经济响应，未声称全量原始验收。

主动买字段原生存在，可按已登记 quote 口径构造占比和不平衡；total−buy 为同口径主动卖补集。实际 collected_at 为 2026-09-26 历史补录，available_at 是周期结束下界；历史每天 00:15:01 到达未证实，严格 PIT/实盘可用时间未验收。只给予历史重建、明确到达假设的条件诊断准入，不授予策略有效、收益或可交易状态。两个币不是大量独立横截面样本，quote 价格加权和同期价格冲击须保留识别边界。

交付：`.local-dev/project/data/research/diagnostics/btceth-flow-field-admission-20261010T155243Z/README.md`、`field-contract.json`、质量/原始抽样/受保护输入证据及 `SHA256.json`。16 文件共 441639 字节；合同 SHA-256 `15f1308d34d513ae34f133a33a4582184bebab4c2a1a34193e404ff43479922c`；seal SHA-256 `53ed7a8d9848233dde7e7712485f1a393cdd936995db554565a4a485b667e484`。冻结面板 SHA-256 `5ecff9cdcfa924c55d20a9b1455e03db2978e5add4a157108717f8cd4d0f2a4e`，input-manifest SHA-256 `07f0e61ac56eae49991773816737bfad5c2a19fdd97457c8f81e579cb7f17e8b` 已核对。

源 manifest、面板、既有预登记和实现文件哈希未变。只新增本诊断包和新记录，不碰其他任务修改；未读截止日后价格、未计算收益/标签、未采新市场数据、未安装/重启/交易。运行中容器及 PG/Qlib/H5 主动成交字段传播仍未验收，未绕过 Docker 限制。下一步交方法会话继续原预登记；真实到达验证、逐笔重建、扩币/合约/保留段均须另定授权范围。
