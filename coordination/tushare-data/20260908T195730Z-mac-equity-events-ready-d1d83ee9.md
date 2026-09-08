# 股东与事件7合同交接
- Mac remaining_markets，codex/tushare-other-markets，delta171398a052dbe6c36ac274641b0687a5fbf8d652；合入父b199eab后的独立两新文件，worktree clean。接续20260908T194845Z-mac-equity-events-start-2b3a4079.md；无运行模块修改/生产访问。
- 导出EQUITY_EVENT_CONTRACTS、iter_equity_event_jobs、equity_event_prerequisites；父注册group equity_event/enable_equity_event，config equity_event_apis、equity_event_history_start（str/API映射，回退history_start）。复用stocks原始并集，含退市/BJ；catalog中本批67输出字段全部extra_fields，权利全部unprobed，未知cap不能算完整。
- 日期：dividend不支持start/end/period，存量每股{ts_code}取全源历史，最近7日ann_date与imp_ann_date双公告增量；既知首日20000101，不以配置日期伪造供应商范围过滤。单股满2000需要合法公告日拆分，合同不自动发明游标。
- stk_holdernumber/trade/repurchase的start/end均公告范围（月分区）；holdernumber输入enddate是截止日，输出end_date也是截止日，不能混作公告日。repurchase无ts_code输入及股票fallback，2000仅无参数默认/保守报警；stk_holdertrade补隐藏begin_date/close_date，不过滤IN/DE或C/P/G。
- share_float历史start/end是解禁日（月范围），另按同历史跨度逐ann_date回填及最近7日ann_date增量，均不限定未来float_date，覆盖过去公告未来解禁的记录。无offset或假设未来截止日；首日未知保留gap。
- top10_holders/floatholders ts_code必须；start/end为报告期。历史按每股年度、最近400个自然日报告期重取；未知首日另每股无日期发现。文档无数值cap，1000仅运行报警(row_cap_verified=false)，非供应商上限保证。旧于400日的迟发修订另记refresh_gap，不假称已捕获。
- 键：holdernumber(ts_code,ann_date,end_date)正常latest；dividend(ts_code,end_date,ann_date,div_proc,imp_ann_date,record_date,ex_date,pay_date)，holdertrade(ts_code,ann_date,holder_name,holder_type,in_de,begin_date,close_date)，repurchase(ts_code,ann_date,end_date,proc,exp_date)，share_float(ts_code,ann_date,float_date,holder_name,share_type)，两top10(ts_code,end_date,ann_date,holder_name,holder_type)。除holdernumber，合同preserve_distinct_rows=true；父store必须将已生成_row_identity加进读取去重键，保留无事件ID的同粗键不同事件/原始观察，不能把派生字段送上游。后续真实重复键审计再细化逻辑版本规则。
- 6项纯离线测试及ruff通过：7API/字段/合法参数、禁止伪分页/别名、分红全代码发现、最近优先、公告与解禁双轴闰日精确覆盖、报告期历史+400日无重叠覆盖、stock缺失不停独立公告请求、未知首日/全集/修订缺口、错误输入与惰性流式规划。
- 父下一步cherry-pick delta、注册与store身份模式/镜像模块/配置签名和family隔离，再做有界真实样本；本批不等于全目录或已获权限。
