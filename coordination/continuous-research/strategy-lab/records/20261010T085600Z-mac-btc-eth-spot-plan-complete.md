# BTC/ETH 现货基线：设计完成，等待父会话协调

- 时间/节点：2026-10-10 08:56 UTC，Mac，研究方法会话；接续 `20261010T084911Z-mac-btc-eth-spot-plan-start.md`。
- 状态：计划与现有实现/旧复核索引完成；无策略执行、行情载荷读取、Docker 或服务操作。
- 产物：`.local-dev/project/data/research/diagnostics/btc-eth-spot-baseline-20261010T084911Z/PLAN.md`；SHA-256 `f6af93c79d7dd2dca08eec1f579db7739123afae040711a1673753faf49243f9`。
- 数据交接：只读 `btceth-spot-data-contract-20261010T084904Z` 三文件；contract SHA `a5b3c906593d48dd013077e826cd749491c6f770b459ea35406a780d4a55dd01`。固定源为 `binance-20261010T001517685958Z-7c1f6c5ec7`；开发 UTC bar 截至 03-24，后续价格不读，最终币安留出仍待登记。
- 固定提议：现有 CryptoAlpha MA21，两币各 5000 USDT 独立 sleeve；下一日 close 代理，统一估值期末；主 10bp 费＋5bp 滑点，压力 20＋10；三主组＋两压力组合，共五个组合账本（十条 sleeve 轨迹）。父会话明确收窄成本，覆盖数据合同的九格建议；保留合同原件，未改动数据会话文件。
- 证据等级：当前规则/费用代理开发比较，不声称历史 PIT、准确成交容量、盈利或盲测。既存 CN runner/broker 不能直接当现货撮合入口，下一批先证明代理规则消费与逐笔账本正确。
- 尚待：资金费 S02 精确路径/ID、既有策略接触清单、开发使用分区定向全字段/哈希验收、实际现货消费者或最小隔离适配、父会话执行批次协调。
- 检查：`git diff --check` 通过；四个既存 tracked 修改列表保持原样；只新增本方法计划及两条唯一记录。S03 新变体与搜参停止，GLM 暂停未恢复。
