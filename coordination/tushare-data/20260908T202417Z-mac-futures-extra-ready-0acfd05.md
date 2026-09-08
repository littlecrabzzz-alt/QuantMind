# 期货补充7纯合同 ready
- Mac remaining_markets / codex/tushare-other-markets；已合入父e8ee822并保留旧提交。只pick增量0acfd056659879a569b753e51347ea8df409947c，2新增文件，无运行模块修改。
- 7 API/85官方字段：fut_trade_cal(467)、fut_daily_adj(492)、fut_weekly_monthly(337)、fut_holding(139)、fut_index_daily(468)、fut_weekly_detail(216)、ft_limit(368)。官方https://tushare.pro/document/2?doc_id=<id>已重读，492经TLS验证httpx取文档；无API请求/凭据/生产访问。
- exports FUTURES_EXTRA_CONTRACTS / iter_futures_extra_jobs(config,today,identifiers=None) / futures_extra_prerequisites；预期父group futures_extra。config futures_extra_apis、futures_extra_history_start(str或API map，fallback history_start)、planning_epoch。所有permission_status unprobed；独立权利没有文档证明，independent_permission=None；周月线积分未知。
- 历史/近期惰性round-robin；未知下界仅近期并留gap；ft_limit文档2005年、weekly_detail文档2010-03，以year/month精度floor保存。日截面全市场含假期不套股票历；日历保留休市/五列交易所外GFEX覆盖gap及pretrade_date隐藏字段，不等于夜盘session。
- weekly_monthly freq必填week/month；key含trade_date(周期标签)+end_date(计算截至)+freq+ts_code，近期40天至本月末/下一周五较晚者以覆盖部分周期。weekly_detail按供应商YYYY+01..53，不声称ISO；近期当前/前一年全部106个week，历史其他年逐week；保留raw week不补零（官方旧样例20199），amout_yoy拼写保留。不能用通用day splitter或offset分页。
- 饱和fallback已有families：adj→futures_continuous；weekly_monthly/ft_limit→futures；index_daily→futures_indexes(.NH，需父增发现)。发现保留过期/原始大小写，非完整历史证明。
- fut_holding不能裸start/end，按trade_date查询；SHFE包含INE，symbol是合约/品种而非ts_code。日截面2000若饱和，需父未来实现exchange+symbol观测组合分片；当前显式gap，不注册会遗漏或跨交易所误分的通用fallback。broker非稳定ID，preserve_distinct_rows=True + _row_identity，隐藏exchange必须全字段请求。
- 7离线测试通过，ruff format/check与git diff --check通过；工作树clean。归属释放，下一步父核查并独立集成（registry/pipeline/store/mirror及capability实测）。
