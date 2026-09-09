# 跨资产六接口运行候选

纯合同见 [接口说明](tushare-cross-asset-extra-intake.md)。`cross_asset_extra` 已通过既有 registry、planner、归一化、固定版 reader 和 Mac 模块安装清单接线；仍默认关闭。本提交不改变生产配置、权限、目录台账、发布调度或实际采集状态。

| 接口 | canonical ts_code | source_ts_code |
|---|---|---|
| idx_factor_pro | IDX:801010.SI / IDX:CI005001.CI | 原 SI / CI / 大盘代码 |
| fund_factor_pro、etf_limit | FUND:1500011.SZ / FUND:510300.SH | 六/七位原基金代码 |
| cb_factor_pro | CB:T123456.SZ / CB:123456.SZ | 历史 T 与普通代码分别保留 |
| index_global | GIDX:HSI | 原国际指数标签 |
| sz_daily_info | SZBOARD:中小板 | 原中文/ASCII 板块名 |

前缀只适用于这六个数据集，避免旧股票处理误判同形代码。ETF 与基金共享 FUND:，旧家族不改。显式 `code_field=source_ts_code` 可按原代码查询这六者；旧股票 reader 对原 suffix 代码的保护仍在。字段内部联接需显式证券类型与源代码，不凭字符串相似自动合并。

全部 296 列（含 4 隐藏列）、源 null / 未知列、原始金额与复权语义进入原文和 Parquet；`source_ts_code` 与原行 `_row_identity` 逐字/逐行验证。reader 固定默认 `trade_date`，不会因为未来多出 `ann_date` 或 `trade_date_doris` 改变日期轴。元数据包含完整字段描述、隐藏标记、单位/复权/历史/PIT gap 及 namespace。

发现使用隔离的 cross_asset_* 集合，纳入旧目录和所有已存 attempts 的源代码，不扩大旧 stocks/funds/bonds 家族。中信成员只提取 l1/l2/l3 指数代码，不把成员股票当指数；当前国际指数种子及中文历史板块保留，仍不证明历史全集。`.OF` 从场内 outbound 候选排除而原发现数据仍保留。配置依赖由已有动态 planning signature 自动包含 `cross_asset_extra_apis/history_start`；纯合同月份历史与近期优先由原调度器执行。

全量字段/默认与显式日期/按原代码过滤、来源行哈希、版本与 as_of、7 位基金/历史 T/SI/CI/国际/中文命名空间、默认禁用、配置签名、发现隔离、已观测父码补入和重入、合法日期二分、真实 MockTransport 六请求终端饱和 blocked 路径均有临时目录测试。无上游调用或正式数据写入。缺权限、未知最早日期、单码单日饱和、隐藏字段实际支持及历史 PIT 仍待后续有界真实验收。

```
uv run --offline --no-project --python 3.10 --with httpx --with pyarrow --with duckdb python scripts/test_tushare_cross_asset_extra_pipeline.py
```

父任务串行集成点：registry imports/runtime map/EXTENDED_CONTRACTS/PLANNERS；pipeline imports、normalize 新分支、identifiers、extra gaps 和 family 注册；store 合同映射、metadata/default-date、新家族 source_ts_code 过滤；mirror 仅增加模块复制项。本分支没有改 init/next_job/tick/publish/history-budget，也未改通用 fixture 的最终接口数量，由父合并其他新家族后统一更新。
