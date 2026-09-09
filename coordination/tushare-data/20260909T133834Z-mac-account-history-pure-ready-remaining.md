# 开户历史2纯合同候选交接
- Mac remaining_markets；接续070552Z及父usage续派。原独立worktree复用，基线5d442d3；已重读共享f9fc602 AGENTS/coord。branch codex/tushare-account-history，仅pick188db08935ed9436890541bfd826b64a71371825。
- 只新增 backend/shared/tushare_account_history_contracts.py、scripts/test_tushare_account_history_contracts.py；未改runtime/config/ledger，无云端或上游请求。只纯候选，未注册/启用/采集。
- 导出ACCOUNT_HISTORY_CONTRACTS / iter_account_history_jobs / account_history_prerequisites / project_account_period；group account_history，enable_account_history默认false；account_history_apis、account_history_history_start(字符串或按API字典，fallback history_start)。显式scope的惰性月窗×API轮转；已停止更新，只有history epoch、不做recent轮询。旧端仅合法start_date/end_date，上界夹官方20150529；200801只月级文档边界，不造首行。新端末日未知，用固定today作请求范围。
- 官方164/165 HTML SHA写合同，14全部known fields显式请求、nullable numeric、unknown保留义务；raw date原串为自然键，不合并新旧系列。旧period helper仅验证YYYYMMDD~MMDD七日内形状及12→1跨年，不覆盖date；unknown/非法/更长模式ValueError period_projection_unverified，后续runtime须保留raw并记gap。旧date_field=None，不能把派生期末冒充输入过滤轴。20141229~0102可超请求end20141231；20150508 vs20150529差异保留。
- 1000只local unverified guard，官方cap/rpm/dailyquota未披露；local30rpm非授权。合法range可二分，周期过滤语义/单周期饱和第二维仍gap，不能据低于guard推全集。PIT、停更末日、publicationlag、不同单位及20170210起weekly_hold/trade停披露都保留。
- Python3.10.19：/tmp/quantmind-calendar-factor-test310/bin/python scripts/test_tushare_account_history_contracts.py，9tests通过0.003s；Ruff与git diff --check通过。测试覆盖catalog14列/合法params、defaultdisabled、跨年/闰日/假日、异常拒推、连续月窗首尾、旧上界不假造新起点、scope验证、惰性公平和稳定identity。未跑运行全套，因本批不接运行。
- 下一步父独立review/pick纯候选，再决定runtime日期投影与有限真实权限验证；scope总账义务未削减。
