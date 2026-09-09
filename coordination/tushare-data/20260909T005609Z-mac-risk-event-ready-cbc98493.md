# 风险状态5项纯候选 ready
- Mac remaining_markets；commit1e701c632ba2d25e8da17f88c475879c5454a7fc已push origin/codex/tushare-risk-event，worktree clean。本轮父仅pick1e701c6，不重复基线DC等提交。
- 仅新增 backend/shared/tushare_risk_event_contracts.py、scripts/test_tushare_risk_event_contracts.py、docs/tushare-risk-event-intake.md；scope stock_st397/st423/stk_shock451/stk_high_shock452/stk_alert453。与263+13及152生产+DC2比对无重复/查询别名；未动registry/store/pipeline/ledger/config/production、未probe/enable，注册和全目录覆盖均未发生。
- 全5cap1000、29列默认Y显式请求；stock_st3000分/20000101起/09:20更新且早史不齐，其余6000/历史下界未知，独立权利和频控均未说明；实际rights全unprobed。
- 建议组risk_event，risk_event_apis/risk_event_history_start。st近期pub_date/imp_date分别逐日、历史按已存stocks含T/退市无范围请求；其他API近期7日、显式范围后公平惰性历史，stock_st使用文档floor。源日期/说明/异常period保留。unknown历史、旧修订、PIT、单证券饱和继续gap，不猜offset或未来终点。
- 后续runtime必须：alert风险全集包含ETF/funds+历史stocks+源观测（官方样例513310.SH）；store默认alert日期改为start_date，现有列排序可能误选end_date；st默认pub_date。shock trade_date输出公告日，alert trade_date输入提示起始/输出end_date参考截止，不能拿截止筛掉未来有效期或制造trade_date。官方样例过滤/code-market不一致须真实probe核对。
- 7 tests通过（python3 -S -B scripts/test_tushare_risk_event_contracts.py）、Ruff/diff-check通过，纯离线无Pipeline/凭据/数据。官方5页html+txt在/tmp/tushare-risk-docs/供父/独立review复用；已完成提交push，父另排后续runtime/发布，当前采集持续。
