# Tushare RRG ETF 全窗口固定版审计

`audit_tushare_rrg_etf_window.py` 只读一个显式固定 release，按 SSE 自然日完整日历和 ETF 上市/退市区间核对日线、复权、分红事件、涨跌停价格和沪深 PCF。它不连接 Tushare 上游、不读取密钥、不写数据源或研究状态，也不计算信号、收益或交易结果。

审计范围不是“窗口结束日仍上市的 ETF”。工具保留固定版观察到的全部沪深 ETF，再仅对存在上市日、且生命周期与窗口相交的代码建立逐交易日覆盖包络。缺上市日的记录单列；该包络仍不是完整历史 ETF 池，也不是行业映射的 PIT 证明。

输出目录必须是源码和数据目录之外的新目录：

- `report.json`：固定 release、查询来源、逐日和月度执行点覆盖、阻塞门槛。
- `missing-observations.jsonl`：按 ETF 和连续 SSE 交易位置压缩的实际缺价范围；没有任何补价。
- `collection-plan.jsonl`：Tushare 原始后缀代码及精确参数。日线缺口只允许诊断复查；分红要求持久化终态/空响应回执；PCF 计划在权威历史 ETF 行业映射到位前保持休眠。
- `manifest.json`：上述文件的字节数和 SHA256。

固定发布版只保存有数据的观察，不能区分“请求后合法为空”和“从未请求”。因此 `fund_div` 即使事件稀少，也必须由采集流水账的逐代码终态回执证明覆盖，不能从发布版 0 行推导没有分红。`etf_limit` 是价格上下限，不含可用于 ETF 的停复牌或开盘竞价语义；日线 0 行也不能直接标成停牌。PCF 的 `trade_date` 是清单适用日，不是可核验的盘前 `known_at`，数量也不是持仓权重。

```bash
UV_OFFLINE=1 uv run --offline --no-project \
  --with httpx --with pyarrow --with duckdb \
  python -B scripts/audit_tushare_rrg_etf_window.py \
  --root "$HOME/Library/Application Support/QuantMind/tushare" \
  --release-id data-<manifest-sha256> \
  --start-date 20220901 \
  --end-date 20260901 \
  --output /tmp/quantmind-rrg-etf-window-audit-new
```

## 2026-09-10 固定版结果

在 `data-03885aef45ce7be5ce812f4305734a7c8852646a09cfa567383215d10e5f6d22` 上，969 个 SSE 交易日形成 48 个“月末收盘信号日 → 下一交易日”坐标。1,829 个 ETF 观察中有 1,826 个沪深代码；1,786 个有上市日，1,718 个生命周期与比较窗口相交，另有 40 个沪深代码缺上市日而没有被假定为全窗有效。

同一固定版有 6,740 条中信成员记录，其中 5,504 条仅按未经审定的生效区间候选覆盖窗口结束日；`known_at` 有效记录仍为 0，也没有修订公布证据。重复拉取当前成员不会补成历史可知时间。

生命周期包络共有 1,027,679 个代码日。`fund_daily` 有 1,022,792 个有效代码日，缺 4,887 个，分布于 232 只 ETF 和 1,888 个连续交易日范围；这些缺口可能包含停牌、生命周期边界或源缺失，当前 Tushare 合同没有能权威分类 ETF 开盘可交易性的接口。所有存在日线的代码日都有正 `fund_adj`，所以不需要单独补复权；按生命周期机械期待时仍有 117 个无价格日期也没有因子。51,278 个观察池月度执行代码日中，51,055 个同时有有效日线和复权，缺 223 个。

比较窗内固定版只有 10 条 `fund_div` 事件、涉及 4 只 ETF，但发布版没有空响应回执，不能宣称其余代码无分红。`etf_limit` 没有比较窗内代码日。沪深 PCF 合计只有 2 个代码日，均不在 48 个执行日上；生成的 5,774 个按 ETF/年度覆盖参数全部保持休眠，等待不依赖回测结果的权威历史行业映射。

本轮生成 3,655 个可审查但未入队的候选任务：1,888 个缺价诊断范围、1,718 个分红终态回执任务、49 个 `etf_limit` 月窗。机器证据见 `tushare-rrg-etf-window-audit.evidence.json`。整体研究仍为 `blocked_data`。
