# 涨跌停专题4纯合同交接
- remaining_markets Mac；codex/tushare-limit-extra；增量cd1da8a70637981a99c6af9cf07b2934f0a07664，基线c8783a0。只新增limit_extra纯模块/专属tests/doc三文件，无runtime/生产访问。
- 263+13与144注册对比后选limit_list_ths355/limit_list_d298/limit_step356/limit_cpt_list357；55字段全部核对，8tests与Ruff/diff-check通过。
- THS默认隐藏6列first_lu_time/last_lu_time/first_ld_time/last_ld_time/rise_rate/sum_float，全required+nullable且explicitfields。五池含官方字面“连扳池”，不自动改拼写，需probe验收；D三类U/D/Z，官方明确不含ST，但step官方例含ST，不能共用排除口径。
- 未来group limit_extra；config limit_extra_apis/limit_extra_history_start回退history_start；近期70请求/7日（每日5+3+1+1），惰性历史轮转。THS从20231101、D年边界20200101；step/cpt未知起点只近期或配置范围，不捏造全历史。
- THS/D request_identity_fields=[limit_type]，父runtime接线必须保留请求维度并为store全合同fixture补两API身份映射；不只改148数量。不同源行identity保留、同值multiplicity与池一致性未验证。
- 股票饱和候选limit_securities需并历史/T/退市+历史列表+已观察榜单；cpt .TI独立limit_concepts，rank/nums/up_stat保持源字符串。无offset/limit，终端cap/universe/PIT/旧修订都保持gap。
- 权限一律unprobed；8000以上公布500rpm/日不限，D另5000档200rpm/日10000；运行ceiling50分开。未碰runtime/catalog/ledger/RRG/生产配置。
