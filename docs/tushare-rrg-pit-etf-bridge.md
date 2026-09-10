# RRG 历史成员与 ETF 单点输入桥

`prepare_tushare_rrg_pit_etf_bridge.py` 只读一个显式固定 Tushare release，将现有数据映射为 RRG 研究配置声明的历史成员、ETF 行情、持仓和 PCF 文件形状。它验证一个“月末信号日 → 下一 SSE 交易日开盘”的输入点，不运行信号、收益、回测或研究状态迁移。

## 已接上的结构

| 输出 | 固定数据来源 | 保留的边界 |
| --- | --- | --- |
| `sector_members.parquet` | `ci_index_member` | 映射 `l1_code/ts_code/in_date/out_date`；`known_at` 明确为空，生效区间只标候选，不作为历史可知成员使用 |
| `etf-universe.parquet` | `etf_basic` + `fund_basic` | 只把来源明确为 SH/SZ 且内部代码市场一致的记录列为执行日日期候选；其他市场显式列缺口。当前状态和当前索引映射不回填为历史行业映射 |
| `tushare-execution-point.parquet` | `fund_daily` + `fund_adj` | 只接受精确执行日原始开收盘、成交量额和因子；不补价，成交量保留“手”、成交额保留“千元”，不把有日成交当成开盘可成交证明 |
| `etf_components.parquet` | `fund_portfolio` | 每只候选 ETF 只保留信号日前一自然日或更早已公告的最新一期；同日公告不假定在收盘前已知，季报股票披露不归一化成完整敞口 |
| `etf_pcf.parquet` | `etf_sh_cons` + `etf_sz_cons` | 只保留精确执行日清单，现金和非普通 A 股代码原样保留；不把数量当权重，`trade_date` 不替代清单公布时刻 |

输出目录必须是数据和源码目录之外的新目录。所有 Parquet 带固定 `release_id` 和 `blocked_data` 元数据，`input-report.json` 记录精确查询、物理分区数和缺口，`manifest.json` 固定所有产物的字节数及 SHA。脚本禁止 socket、DNS 和密钥读取；缺少某一已知数据集时生成空结构和显式 `dataset_unavailable`，不会回退访问上游。

## 仍然阻塞 RRG 的证据

这条桥把“数据已落盘但研究配置没有可消费文件”缩小为明确的结构输入，但不会让 `blocked_data` 变为通过：

- `ci_index_member` 没有调整公告或其他经核验的 `known_at`，`in_date/out_date` 和本系统采集时间都不能替代历史可知时刻。
- ETF 历史池及行业映射还没有带版本、有效期和公布时间的权威来源；脚本不会从名称、当前跟踪指数或收益表现猜映射。
- 单执行日不能证明 2022-09-01 至 2026-09-01 的完整价格/复权/分红/交易状态；实际开盘成交约束仍需独立验证。
- `fund_portfolio` 是定期且可能不完整的股票披露，PCF 是申赎清单；两者不能互相替代，也不能直接视为完整行业暴露。
- PCF 页面说明盘前披露，但没有可供当前合同核验的逐版公布时刻；历史修订仍需保留。

实际研究下一步应先取得历史中信成员调整公告/版本证据，以及不依赖回测结果选择的 ETF 行业映射；然后用新固定 release 按整个比较窗口逐点复用本合同。价格缺失保持缺失，不能 `ffill` 执行开盘。

```bash
UV_OFFLINE=1 uv run --offline --no-project \
  --with httpx --with pyarrow --with duckdb \
  python -B scripts/prepare_tushare_rrg_pit_etf_bridge.py \
  --root "$HOME/Library/Application Support/QuantMind/tushare" \
  --release-id data-<manifest-sha256> \
  --signal-date 20260831 \
  --execution-date 20260901 \
  --output /tmp/quantmind-rrg-pit-etf-new
```

测试使用合成固定读取器验证：下一 SSE 交易日、成员空 `known_at`、严格早于信号日的持仓公告、原样现金 PCF、缺执行价不填充、坏区间/坏价格保持阻塞、输出保护和所有研究/交易状态不升级。

## 2026-09-10 固定版实测

本地只读镜像 `data-2c8715f9920400555ccab3f739c982938cb127f72db1a1c6c0bb18378b6f1662` 上，以 2026-08-31 收盘为信号、2026-09-01 为下一开市日运行约 34 秒，`upstream_calls=0`：

- 6,740 条中信成员历史记录映射完成，其中 5,497 条仅按未审定的区间口径覆盖信号日；`known_at` 有效记录仍为 0，PIT 门槛保持阻塞。
- 1,829 个 ETF 观察代码中，1,648 个 SH/SZ 代码满足上市/退市日期候选；`158008.OF` 因市场不受交易所 PCF 合同支持而单列，不混入执行池。
- 精确执行日有 1,645 个 ETF 开收盘，且这些行都同时存在正复权因子；`SH511670`、`SH511920`、`SZ159578` 没有执行日价格，未填充，需再用上市状态/停牌/源缺失证据分类。
- 550 日公告搜索窗读到 373,264 条 ETF 持仓记录，901 个 ETF 形成严格早于信号日的最近披露，共输出 39,543 条成分；仍按部分披露处理。
- 沪深 PCF 在精确执行日均返回 0 行，现有 9 月 4 日清单未倒填到 9 月 1 日。完整比较期 PCF 覆盖继续是明确采集缺口。

固定产物位于 `/tmp/quantmind-rrg-pit-etf-final-20260910T0335Z`；`input-report.json` SHA256 为 `897f3720f6c9530c6788c046c6d7a8033af13bdad42b26a24fc8f9aa95457b8c`，产物 `manifest.json` SHA256 为 `db2993de97236fa71f9ac10f8dbde543062466caa7edda26a081bff2645f9f04`。机器可读摘要见 `tushare-rrg-pit-etf-bridge.evidence.json`。
