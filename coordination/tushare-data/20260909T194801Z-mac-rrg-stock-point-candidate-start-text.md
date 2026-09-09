# RRG线C：可复跑单时点输入候选
- 基线已在独立worktree合4446d36，最新AGENTS/RRG/Tushare进度已读；仅拥有新scripts/prepare_tushare_rrg_stock_point.py、专属test及短doc。不碰研究case/config/笔记、runtime或生产。
- 复用既有/tmp ca7c输入验证与固定作者_up_flags，补固定release参数化、两窄端点窗、可验证原值/复权连接、缺项保留和SHA清单；不行业聚合/排名/回测，不构造known_at。
- 当前Mac指针只读取一次并固定0e961a886dafaefd91941dd113039652c294c1ccf0a60d4bb36aae15236b7c82。清单显示ETF日线1630/复权2923/持仓13299/PCF1757份Parquet观察；这是已有物理分区数，不是历史完备性。后续实际单点复跑可先使用已验ca7c作等价回归。
- 全程禁止socket/secret/SQLite；不执行Tushare或云写，输出仅新/tmp目录。历史成员可知时间与ETF可交易口径维持blocked_data。
