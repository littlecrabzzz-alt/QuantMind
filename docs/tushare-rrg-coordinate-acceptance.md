# 固定 Tushare 切片到 RRG 坐标

2026-09-09：坐标消费技术验收通过，可与全目录历史回填并行。整体研究仍为 `blocked_data`。本次没有择优选股、收益回测、策略发现或研究状态写入。

新增 `scripts/verify_tushare_rrg_coordinates.py` 复用现有 `verify_tushare_rrg_slice.verify` 和 `tushare_store.read_dataset`，先核验固定 release，再把 `ci_daily.ts_code/trade_date/close` 转为日期 × 行业宽表，按 `trade_cal` 的 SSE 开市日对齐。采用已核验的 30 代码审计清单，排除综合、综合金融后，28 行业同时作为候选与等权基准；缺日或缺价直接失败，无填充。

直接调用[作者冻结版本的 factor_algo.py](https://github.com/hugo2046/QuantsPlaybook/blob/558536af13715aa13fd2131eaf90c70d32108a38/C-%E6%8B%A9%E6%97%B6%E7%B1%BB/%E7%9B%B8%E5%AF%B9%E6%97%8B%E8%BD%AC%E5%9B%BERRG%E8%A1%8C%E4%B8%9A%E8%BD%AE%E5%8A%A8/src/factor_algo.py) 中 `equal_weight_benchmark` 和 `compute_rrg`，没有另写算法。已从该 immutable revision 下载并逐字节比对本机文件；SHA256 固定为 `e40e22afe36ad61215f66a48e0e16d64f384ac04c465cf4db28f24388dd78402`，不匹配则拒绝执行。基准是行业日收益等权累乘；比例回看 220、动量回看 60、两次平滑各 20，对应 318 个预热间隔、至少 319 个价格观测。

现有 `market_analysis/rotation.py` 是动量/资金流/成交量复合评分；`frozen_research_worker.py` 使用个股模型与不同成交轴，均不承担本次 RRG。用户研究配置仍指向旧 QuantDB，保持原文件，只读其冻结协议。当前脚本是技术验收与坐标出口，尚未接入研究登记或 GUI。

## 最短独立复验

在包含本提交的仓库目录执行；所列三个输入路径必须存在，输出必须是新建的仓库外临时目录。`UV_OFFLINE=1` 只复用已缓存依赖，脚本运行阶段封闭 socket/DNS 和密钥读取；不连接 Tushare、云端或数据库服务。

```bash
UV_OFFLINE=1 uv run --no-project --with httpx --with pyarrow --with duckdb --with pandas python -B scripts/verify_tushare_rrg_coordinates.py \
  --root '/Users/lizeyu/Library/Application Support/QuantMind/tushare' \
  --release-id data-6e00837911a40223d75d7e4e7b770b4b60b4b7c9f2d208091c6e343f7283bee6 \
  --config '/Users/lizeyu/Documents/ChatGPT/投资/QuantMind/config/rrg_sector_rotation.json' \
  --author-source /tmp/quantmind-rrg-author-hdjyrhn1/author/src/factor_algo.py \
  --output "/tmp/quantmind-rrg-coordinate-review-$(date -u +%Y%m%dT%H%M%SZ)"
```

输出 `coordinates.csv` 只包含交易日、行业代码、两维坐标及 release ID；`report.json` 包含切片审计、输入/消费代码哈希、运行版本、因果性检查和月末映射。脚本不跟随 CURRENT，不加载作者 DuckDB/回测层，不产生源码 pycache，不改输入数据。

## 本轮证据

- 最终产物：`/tmp/quantmind-rrg-coordinates-20260909-final/`；报告 SHA256 `f6918cc7d445ba4e8c3745c3f830dfc86ce272ee8151cb272647ae24145e5f60`。
- 配置 SHA256 `c44c31d10f03ebea641481c3f8a2d147fddd12c2b1cd84300ef54df141ec5632`；含预热的价格为 28 × 1,286 = 36,008 行，比较期 2022-09-01—2026-08-31 为 28 × 968 = **27,104 行坐标**，首有效动量恰为 2022-09-01。
- 在 2022-09-01、2024-08-29、2026-08-28 截断历史重算，及扰动各截点之后的价格，均不改变此前结果。逐行业价格缩放不改变坐标；相同走势在预热后为中心 100；观测不足、缺价/空价拒绝；源行顺序反转结果一致。相同数据复跑 CSV SHA256 均为 `66d4ca27445090b528f346499aff1a8d661771c57b7676dc84b1d5d0be83b0e6`。
- 额外隔离负例：错误作者源码指纹、价格重复键、配置作者 revision 不匹配均拒绝；ruff 通过。运行版本 Python 3.12.12 / pandas 3.0.5 / numpy 2.5.3 / DuckDB 1.5.5 / PyArrow 25.0.1。
- 48 个月末日期中 47 个可映射到本切片下一开市日；首个 2022-09-30 → 2022-10-10。2026-08-31 之后的开市日超出已核验切片，明确留空，不以当日开盘代替。此映射不模拟成交。

## 后续最小依赖

坐标消费现在无需等待其余市场/文本全历史。父任务可先以相同 release 和源码复验，再把这个固定读取入口接到隔离的 RRG 展示/研究输入；固定 input release，升级时另建输出。

进入完整研究前仍需官方历史中信分类及指数口径/修订证据；扩散度另需历史成员 `known_at`、可比个股复权价与自由流通市值；ETF 层另需历史池、暴露和可交易开盘语义。月末最后一日的下一开市日需单独补证。象限边界、并列排序、持仓/现金权重和独立测试窗口仍待冻结。当前价格因果性通过不证明供应商历史数据满足 PIT；不更新任何研究准入门槛。

更完整缺口分工沿用 `coordination/tushare-data/20260908T205934Z-mac-rrg-consumer-review-ready-cce7c93d.md`，本记录只增加实际坐标闭环证据。
