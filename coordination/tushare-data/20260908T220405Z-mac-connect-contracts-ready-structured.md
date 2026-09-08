# 互联互通/板块资金流5纯合同交接
- Mac/codex/tushare-connect-contracts；基于父fef5233；候选bcd9e4e69b28442d7062f95ca30ff26bcfc5f2fe。
- 归属释放：仅新tushare_connect_contracts.py、test_tushare_connect_contracts.py、docs/tushare-connect-intake.md。未改registry/pipeline/store/ledger/生产，未探测权限。

实际registry未注册5项：stock_hsgt398、hsgt_top1048、moneyflow_cnt_ths371、moneyflow_ind_ths343、moneyflow_ind_dc344。已注册moneyflow及原supplement三资金流跳过。moneyflow_hsgt47/ggt_top1049/ggt_daily196/ggt_monthly197当前官网直取HTTP200+23字节正文404；官方GitHub索引仍有名字而其196/197 Markdown链接404。缺正文不等于停更/没权限，暂保留source_missing/review_required，未凑6项或用缓存造合同。

接口 CONNECT_CONTRACTS / iter_connect_jobs(config,today,identifiers=None) / connect_prerequisites(identifiers=None,enabled_apis=None,config=None)。配置connect_apis、connect_history_start（日期或API字典/回退history_start）。最近7日全部4条港通方向、2类十大成交市场、3类DC板块先规划；随后公平历史。资金流历史按月，可日级bisect；十大成交必须exactday。stock_hsgt最早20250812，其他最早未文档化。运营50/min与未知官网数值限频分开；hsgt_top10无积分/数值行限文案，1000只未验证报警阈值。

后续runtime需连接connect_<api>的源观察发现，保留原type/content_type/market_type继承，不拿A股列表替代.HK/.TI/DC代码。所有分片观测全集/PIT/旧修订仍gap。398官方类型枚举被旧catalog误纳为input，本纯合同仅保留真实5输入参数；其示例混type单独标记过滤一致性待验。金额单位THS亿元/DC元/十大成交元分开保留。

5个离线测试通过（包含多参数化断言）：字段+注册无副作用、枚举修正、全日期和全类型无重叠遗漏、闰月、无起点仅近期+gap、负数空值不改写、长历史惰性/非法输入。Ruff/diff通过。公开原始HTML仅/tmp/quantmind-connect-docs，精确sha和官方链接已写提交文档；无源API/凭据。父下一步选择runtime接入/真实权限探测，本候选不声称运行或存储验收完成。
