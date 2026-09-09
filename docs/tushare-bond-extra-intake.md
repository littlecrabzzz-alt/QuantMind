# 债券与可转债补充 8 接口：纯合同候选

基线 `30b3194` 的 263 个目录项、13 个发现项与 192 个运行接口（185 extended + 7 bootstrap）逐项比对后，本批均未运行接入。只新增纯合同/规划、专属测试及本说明；不修改总目录、覆盖台账或原 scope。`cb_basic/issue/call/rate/daily/price_chg/share/factor_pro` 已有合同，本批不重复。未来 family 为 `bond_extra`，导出 `BOND_EXTRA_CONTRACTS`、`iter_bond_extra_jobs(config,today,identifiers=None)`、`bond_extra_prerequisites`；尚未注册、探测、启用或部署。

| API / 官方来源 | 全字段 / 默认隐藏 | 参数与分区 | cap / 文档门槛 |
| --- | --- | --- | --- |
| [top10_cb_holders](https://tushare.pro/document/2?doc_id=459) | 6 / 0 | 必填 ts_code，可多值；period 或 start_date/end_date 按**报告期**过滤 | 3000 / 5000 分 |
| [cb_rating](https://tushare.pro/document/2?doc_id=458) | 8 / 0 | 仅必填 ts_code，支持多值；无日期参数 | 3000 / 2000 分 |
| [repo_daily](https://tushare.pro/document/2?doc_id=256) | 12 / 0 | 可选 code、trade_date、start/end | 2000 / 2000 分 |
| [bond_blk](https://tushare.pro/document/2?doc_id=271) | 6 / 0 | 可选 code、trade_date、start/end | 1000 / 5000 分 |
| [bond_blk_detail](https://tushare.pro/document/2?doc_id=272) | 8 / 0 | 可选 code、trade_date、start/end | 1000 / 5000 分 |
| [yc_cb](https://tushare.pro/document/2?doc_id=201) | 6 / 0 | code、curve_type、trade_date、start/end、curve_term | 2000 / **独立权限** |
| [bc_otcqt](https://tushare.pro/document/2?doc_id=322) | 13 / **13** | code、trade_date、start/end、bank | 2000 / 500 分试用，2000 分较高频次 |
| [bc_bestotcqt](https://tushare.pro/document/2?doc_id=323) | 11 / **9** | code、trade_date、start/end；无 bank/qt_time 输入 | 2000 / 同上 |

共 **70 列，其中 22 列默认 N**。合同保留全部官方输入、输出类型、默认显示、逐字段说明及来源 HTML SHA；required/requested/extra fields 都包含完整列，不能使用 `fields=''` 或只抄示例列。保留未知来源列、null 和原始单位；每列实际返回及历史修订状态均未验证。`yc_cb.yield` 是真实列名，后续查询应按现有机制引用列名，不能当 Python/SQL 关键字遗漏。8 页原文及解析表保存在 `/tmp/tushare-bond-extra-docs/{doc_id}.{html,json,txt}`；测试以仓库目录字段核对，运行不依赖 `/tmp` 原文。

`bond_extra_apis` 显式选接口；`bond_extra_history_start` 支持全组日期或 API 映射，未设置时兼容 `history_start`。**8 页均未给出确切历史下界**，示例日期不是起点。没有范围时只规划有限近期请求并记录缺口。6 个日/报价接口按最近 7 个自然日精确日期请求；YC 每日显式保留 `curve_type=0` 到期、`1` 即期两种身份。未知历史范围不凭空扩成已完成全历史，也不使用 A 股交易日历剪掉银行间或柜台日期。

`identifiers['bonds']` 复用现有可转债发现形状（原始 cb_basic 行或来源代码），包含退市、赎回、历史 T 与已观测旧代码，不能替成普通股票或仅当前债券名单。持有人近期每代码查询上一自然年起至今日的报告期范围，覆盖最近年报/中报的迟披露；显式更早历史范围与近期不重叠，按代码惰性生成，饱和后可按报告日二分，不创造季度数据。评级每代码只查一次全部可得历史并随近期 epoch 重查；配置的历史日期不能转成非法评级过滤参数。新发现及早期修订仍需持续补齐审计，已返回报告期集合不是全集。

后续接线须保留以下边界：

- 可转债 `CB:`、回购 `REPO:`、普通债券 `BOND:`、曲线 `YC:` 使用原始代码；SH/SZ/IB/BC 和无后缀曲线标签不能误判成股票。所有源字段保留，跨场所同券映射未验证。日频初始请求不需要猜主数据；饱和扇出分别依赖 repo_instruments、bond_trade_instruments、bond_curves、otc_bonds 的历史来源发现，不能套 stocks 或把 CB 名单当全债券全集。
- 持有人输出 end_date 是报告期，无公告时间，hold_amount 是万张、hold_ratio 是百分比。评级 ann_date 是评级发布、rating_date 是评级评定；其示例错误调用 cb_daily，且没有展示 rating_way/rating_type，**不是别名或省列依据**。
- bond_blk 的成交量/额虽描述为累计值，样例同券同日有多条不同成交，不能聚合成一行。明细接口目前仅深交所；上交所明细在 bond_blk，两者互补但不可互相冒充。vol 的万股/万份/万张/万手没有逐券单位映射，仍未知；价格元、金额万元按来源保存。同值成交次数无法仅靠内容哈希证明。
- 回购 OHLC、weight/weight_r 是百分比利率，不是股票价格；期限字符串和交易笔数保留。YC curve_term 是年、yield 是百分比；输入示例 1001.CB 与输出 101 不一致，示例请求 type0 却展示 type1，代码映射与过滤效果均待实测。不能凭浮点期限猜完整期限网格。
- 柜台两接口提供可按历史日期查询的报价，不引入实时或分钟采集。qt_time 与报价日期不是公告时间；最优报价无日内时间，不能还原所有盘中状态。买卖方向是投资者视角，全价的币种/面值/应计利息口径未完整说明，不擅自换算。报价机构及成熟期限原文保留。
- 8 个接口均无合法 offset/limit/page。满 cap 只能用文档支持的日期/代码拆分；持有人单代码单报告、评级单代码、交易单代码单日都可能终止为 gap。柜台 bank 和 YC curve_term 是合法额外过滤，但其历史全集及通用第二维扇出未实现；qt_time、持有人排名和评级时间不能伪造为请求参数。

权限统一 `unprobed`，本地 30 rpm 是保守上限，不是供应商配额。10100 分或已购新闻等独立权益均不证明 YC 权限，也不证明其他 API 已授权。近期覆盖、原文归档或注册不能证明 PIT、全部上游字段或全历史完整；合同保留这些缺口。

验证：7 项纯测试通过，覆盖全 70 列/22 隐藏列、输入与目录一致、历史/T 代码、报告和评级日期轴、YC 双身份、闰日及历史近期无重叠、缺发现/缺起点、非法参数拒绝、惰性公平生成；Ruff 与 diff check 通过。只使用隔离源码和合成标识，无生产或 Tushare 数据请求。
