# RRG 最小数据依赖与40个既有任务状态

- structured/Mac，完成独立只读审查。只写本条与/tmp证据；未修改研究文件、ledger/progress、正式DB/配置/优先级，不拉上游。现有研究仍blocked_data。依据现行RRG config、薄适配文档、原作者冻结算法与已验固定报告；不等待263接口/附件/海外/技术指标全历史。
- 核验输入报告SHA490dad76ec985055155534cdcb7662de4b07684850de4666a3c356669331ab8f、作者factor_algo SHAe40e22afe36ad61215f66a48e0e16d64f384ac04c465cf4db28f24388dd78402。未重新计算策略/全量验收。

## P0：坐标可消费，数据不再等待

已有固定data-6e00837911a40223d75d7e4e7b770b4b60b4b7c9f2d208091c6e343f7283bee6，ci_daily CI005001–CI005030（规范源代码；排除029/030后28行业），20210517–20260831共1286交易日，36008有效价格行；trade_cal SSE含318预热。比较20220901–20260831已产生27104坐标且因果性通过。薄适配输出 `/tmp/quantmind-rrg-case-inputs-20260909-final/` 已含价格/日历及48月末映射，补充日历固定e138明确20260831→20260901。无需重新采集这段ci_daily/trade_cal；可把该既有输入交隔离展示/研究契约审查，不能称GUI/完整research_case已接或解除语义gate。若做最终月末的次日行业执行示例，另定点核查ci_daily的20260901 open；这不是坐标计算前置。

## P1：最快新增扩散度数据包，只验一个时点

冻结作者实际公式为close对220交易日前的涨跌，再MA20；自由流通加权另用当前日市值。先仅准备20260831一个时点数据包，不运行策略，也不宣称PIT通过。

- 当前20交易日20260804–20260831的daily/adj_factor/daily_basic，已在RRG111真实81done/30休市empty中，全部303文件于Mac固定cc8闭合；三接口包含13+3+19列（35），无须重拉。原111只证实完整窗口内22个非空研究日期，不是1286日全历史。
- 对应220日前的20交易日严格由已验SSE日历位置推导：`20250903,20250904,20250905,20250908,20250909,20250910,20250911,20250912,20250915,20250916,20250917,20250918,20250919,20250922,20250923,20250924,20250925,20250926,20250929,20250930`。
- 精确候选为上述20日分别 `daily {trade_date:日}` 与 `adj_factor {trade_date:日}`，保留原完整fields、原rowcap、history epoch；无ts_code过滤的合法全市场bulk，随后消费只取28行业当时成员并集，包含退出/退市代码，不拿当前stock_basic作全集。不需要该滞后端的daily_basic。
- 04:16:44Z既有quantmind业务入口只读核查：40个精确history任务全部已经存在，pending/priority45/tries0/retry_after0、result null、attempts0、group structured；missing0、done待发布0（仅这40身份）。通过原20210517两已验job合同换日期推导逻辑/主键，EXPLAIN为jobs主键搜索；attempts走job_id复合主键。查询0.004秒，无全DB扫描。完整job_id/logical_key/params/fields在 `/tmp/tushare-rrg40-existing-readonly.json`，SHA `be230d3dfdb0c21f446f06610dc3f8b32ceae8d303d8eafe59a34b7757b0d0f0`。
- Mac固定data-86aebb78840094da306bdb92aaa89876e199f55733c727a9e1068927869a63e4 actual reader按20250903–30查询daily/adj均0行，0.808秒，禁socket/DNS/SQLite；`/tmp/tushare-rrg40-mac-existing.json` SHA `fe3ef3bfe7c177fa0331001048b97ca9195787e33040f2ac975e69326430d844`。云端指针当时2b34…仅读取指针，不据此声称全部其他epoch/分片无数据。
- root下一步可用原有限优先调整机制按这40主键重查仍pending后处理；保留任务/tries/result/epoch/gates/fairness，**本次没有实施**。完成后按固定版验收raw/obs/Parquet和局部输入，再等自动镜像。40是初始请求数上界，不含饱和扇出/失败，也不是到货时间保证。
- 消费必须保持20250903–20260831完整240个交易日索引骨架，不能把40个有价日压成40行再shift220；未采中间值不得填充或冒称逐日扩散度已算。member有效性需覆盖当前20日，历史可知性另验。股价比较用同口径close×adj_factor比值；权重用当日未复权close×free_share×10000（free_share万股→元），不能把circ_mv等同free-float或用复权价乘股数。null/上市不足/停牌/未知市值逐项保留；只做局部数据包不能改算法处理规则。

## P2：回测/PIT必须并行补证

- ci_index_member：28个l1_code分别is_new Y/N（保留另外2行业作全分类审计），先复用已有结果、看饱和闭包与成员并集。in_date/out_date是有效日期，既有观测没有可填的历史known_at；需指数发布方历史分类版本/调整公告及公布时刻原证据。不能把2026 fetched_at倒填2021 known_at，也不能把THS/DC/SW成员混成中信。
- 全开发复现20210517–20260831，股票行情/因子覆盖可按已验1286开市日补齐；粗上界3×1286=3858个bulk日请求，已有研究窗三API各22非空日，未被本次完整证实的候选余量至多3792个“待查覆盖”API/日，**不是实际pending数量**；真实新采可能已覆盖，先按既有manifest和作业复用。更小端点法仅适合有限时点输入，不是全日路径/执行回测替代。
- 行业分类版本、指数编制/修订口径、成员known_at与独立测试期、同分排序/权重/现金约定仍未核准；数据PIT与实验设计分别处理，不能靠下载全库自动解除。

## P3：ETF映射另冻结小池，再定向验收

先从已存etf_basic L/D/P、fund_basic E含退市、etf_index及fund_portfolio带ann_date/end_date的历史暴露构造候选，不凭当前名称指定ETF名单；当前config没有冻结ETF代码，故本次不猜具体基金或宣称可交易。代码池明确后才排：fund_daily/fund_adj/fund_div自上市起与比较窗相交，覆盖20220901–20260901的持有/执行期；fund_portfolio从首次信号前最后已公告期至结束，缺披露不回填；etf_sh_cons/etf_sz_cons按实际交易日与历史池核验，保留现金行。来源PCF已有部分原文，不代表完整历史或公布时间。etf_limit是本轮候选尚未实测；涨跌停、停牌、成交量/单位、开盘可成交与成本必须另验，不能把limit接口可用等同可交易。

现ledger对daily/adj_factor/daily_basic仍显示implementing/unverified，落后于111已验实物证据；本次只指出不改全局台账。新公平消费已修复旧“近期永久压历史”的机制，09:15旧饥饿诊断不能直接当当前原因；当前40仍pending是本次主键实测。开发/数据补证可并行，账户限流仍共享，不能承诺多worker线性提速。归属释放。
