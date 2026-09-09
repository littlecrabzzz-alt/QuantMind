# RRG 最小研究输入缺口：已有消费闭环之后的增量

- Mac / text_contracts；独立只读，唯一新增本coord；未改运行代码、研究配置/case、权威数据，未调用Tushare或计算新策略。现有blocked_data保持。
- 依据现行config/rrg_sector_rotation.json、scripts/research_case.py、docs/tushare-rrg-coordinate-acceptance.md及上一轮20260908T205934Z-mac-rrg-consumer-review-ready-cce7c93d.md。本次只更新可证实差异，不重跑30行业价格/日历或坐标算法。

## 最短结论

无需等全量263目录：价格→坐标已通过，下一批应做固定研究输入适配和历史行业定义审查。仅补价格或把PCF列改名不能让整个case解除blocked_data；扩散度、ETF执行还有独立来源/PIT门槛。research_case.check当前对语义门槛始终标unknown，结构齐全最多awaiting_data_review，不是研究验证通过。

## 本轮固定证据与变化

1. 固定e138：data-e1386fc1f304f2ef6ef34d3c59ec99b4f3d1ec34fd49c9841ddd7591a74e1bce，root `/Users/lizeyu/Library/Application Support/QuantMind/tushare`；manifest原字节SHA等于ID，rrg_status=blocked_data/history_complete=False。当前CURRENT/mirror-status已一致为verified的data-0a6ab25c1edd32e087c0919962df21d4fa910a28a98b089e83e0be0b1793c2a2；本审查仍固定e138，不混用新版数据。
2. 已有价格切片报告 `/tmp/quantmind-rrg-slice-parent-20260909/report.json` SHA36c0c9ed2ea0c3a2c91bca7714dc53f06d15b71a991fa8b74b20a15d1b2787d4；28有效行业×1286日=36008价格，318预热始于20210517，比较期20220901—20260831。坐标报告 `/tmp/quantmind-rrg-coordinates-20260909-final/report.json` SHA f6918cc7d445ba4e8c3745c3f830dfc86ce272ee8151cb272647ae24145e5f60：27104坐标及因果性已过。两报告本轮重新核对文件SHA，非重算。
3. 旧报告最后月末下一开市日缺口现在仅需接映射：本轮对固定版14个trade_cal小Parquet逐SHA核验，只选20260831—20260904边界，SSE 20260901 is_open=1；来源含`parquet/5ed4ac8627f76b7335d9cae63bd52cdf17c170ede2e46b77e9a082ee76d6605a.parquet`。可补20260831→20260901日期映射，无需再拉日历；该日行业/ETF开盘价格尚未在本次边界审查中核验。
4. 固定版仍仅daily/adj_factor/daily_basic各1保存分区；daily_basic经SHA验证样本`parquet/2265f9f367412f86231a689c0ac3b65e9a97ed3ef5f8d49c8f8ceba584589bd2.parquet`5549行仅20260908，虽含free_share/circ_mv/close，不覆盖复现窗口。故股票历史扩散度不是单纯改映射。
5. ci_index_member59分区。经SHA验证`parquet/b20b337a46a35a7447ad6db5d57a917798257e57420c3383956d1afad84aa7b7.parquet`8行含in_date/out_date/is_new和三级代码名称，缺known_at；样本有20191202入、20220207出，不能把这些生效日或2026年_fetched_at当历史公布日。
6. 旧“无PCF”已过时：e138有etf_sh_cons474、etf_sz_cons532保存分区。SHA验证样本SH`parquet/5237917a04a50f03d301cc1d51b839e52e60ee4574afd42a12ac80396509dde6.parquet`、SZ`parquet/5103288ad62a0cd7da849837c1ac8f1ec2fed6daccbc2d737fe460dfdd035d6e.parquet`含20260903/04，来源现金行SSXJ/159900.SZ和_raw_numeric_json需保留；这是近端可用证据，不是2022—2026完整篮子或known_at证明。
7. 其他固定版分区数：etf_basic3/fund_basic7/etf_index2/fund_daily1626/fund_adj2920/fund_div884/fund_portfolio8488。计数不代表目标ETF历史覆盖。SHA验证fund_basic退市样本`parquet/514e7cc5afd9b3b4305ab0fb4be0c3f45bb239a8979e016016fadc73baab892d.parquet`有list_date/delist_date/status（例560890.SH在20260401退市）；fund_portfolio样本`parquet/247af0192820508a581498134d01e43c4036ec5dd2d9fb88f3b6e4cc5ea56dc3.parquet`有ann_date20201027/end_date20200930。已落盘但尚未按RRG冻结证券池逐期验收。

## 最小缺口分类与优先采集范围

| 层 | 已有但未接映射 | 来源/覆盖缺失 | PIT/语义不能猜补 |
|---|---|---|---|
| 行业信号 | 固定read_dataset→ci_daily ts_code/trade_date/open/close到IndexCode/time/open/close；trade_cal cal_date/is_open到TradingDate/IsTradingDay；现配置仍旧QuantDB glob，坐标技术脚本未接research_case | 仅定向查20260901开盘是否已存，缺才补ci_daily30代码及该日；既有20210517—20260831价格不需重复采 | 2021—2026官方中信一级历史分类版本、全行业名单/名称代码变化、指数价格/收益编制与修订口径。当前30代码清单只审计冻结，不是官方历史全集证明 |
| 扩散度 | ci_index_member l1_code/ts_code/in_date/out_date可映射成员及生效轴，保留原文；不能填known_at | 优先历史成员并集（含退出/退市源身份）daily(ts_code,trade_date,open,close,vol,amount)、adj_factor(ts_code,trade_date,adj_factor)、daily_basic(ts_code,trade_date,close,free_share,float_share,circ_mv,total_mv)，20210517—20260831，按每段成员有效期加所需回看；原请求仍保留合同全部字段 | 成员调整公告/当时可知时刻缺；官方指数分类/调整公告需原文有效期+公布时间证据，现接口没有可凭空生成known_at字段。free_share×未复权close须先核对单位和自由流通定义，不能直接以circ_mv替代；复权修订时点另审 |
| ETF执行 | etf_basic.index_code仅当前跟踪指数映射；fund_basic退市记录、fund_portfolio公告/报告期、PCF交易日与原现金行已经可做薄适配 | 先按行业覆盖/上市状态冻结小规模验收池、不看收益选券。该池fund_daily open/close/vol/amount +fund_adj adj_factor +fund_div分红/除息/支付字段，20220901—20260901并取期初必要公司行动；stk_limit up_limit/down_limit及suspend_d状态同窗适用性先小样本核对。fund_portfolio取截至每信号日已公告的最近报告（起始2022年公告、必要时补更早最后一期；末报告期20260630），不足保持未解释暴露；PCF etf_sh_cons/etf_sz_cons按交易日20220901—20260901定向验收缺口，历史不可得显式保留 | fund_basic/etf_basic历史修订与当时池、季度只披露部分持仓、PCF适用日非真实公布时刻、指数→中信行业历史暴露、下一日开盘可成交状态/单位/成本均需独立证据。不得把现金行当股票、季度持仓当每日PCF、当前篮子倒填历史 |

ci_index_member优先明确取各l1_code及is_new=Y/N，不只当前Y；现有59保存分区不必盲目重取，先消费固定观测核对每期覆盖。成员known_at/行业分类版本若供应商无字段，不会因全部API回填完成而自动解决；需要指数发布方历史公告/档案，未知保留。

## 不等待全量可马上做的三步

1. 独立输入适配：复用已验坐标入口与固定6e008原报告，另将e138的20260901日历作为明确附加固定输入；记录两个release及字段映射，不在原报告内替换数据。为研究注册准备新版本输入契约/独立输出，避免写旧QuantDB；旧case继续blocked_data。
2. 并行语义审查：冻结官方历史行业定义证据、100象限边界/并列排序/持仓与现金权重。配置已注明比较期是development_replication，独立测试窗口另冻结；本轮不做策略发现/回测或降门槛。
3. 并行小池数据验收：历史成员PIT缺口登记；将上述三股票接口的具体窗口和冻结ETF小池放入父现有采集队列按缺失提升优先级。先验证每个层的最小输入包与负例，不能以pending清零作为准入条件，也不新建重复回填队列。

付费新闻/PDF附件、海外/期货/期权/债券/宏观等全部历史与这批行业信号输入适配无关，继续后台回填即可。要让整体研究离开blocked_data，最终必须补齐该case所声明各层结构并完成独立语义审核；本审查只定位最短路径，不替它审批。
