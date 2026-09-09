# 风险5运行候选 ready
- Mac remaining_markets，codex/tushare-risk-runtime已push且clean；基线e87dc2b。准确父pick顺序1e701c6纯→1e6716afad6614e1e692834822da40471455ddc4 runtime；若已有pure只pick新1e6716a。本分支pure等价621c1fe勿重复。
- 7文件：registry/pipeline/store/mirror风险接线、store159合同fixture、新scripts/test_tushare_risk_event_pipeline.py、风险intake文档增量。没有主planner循环/发布函数/interval/timing/配置/台账/共享主树源码或生产改动；未probe/enable/停写，权限声明unprobed，不宣称采集或覆盖完成。
- 风险组风险股票集合risk_stocks独立吸收历史stocks/listings/tradingevents和ST/异常source；risk_securities再加funds/ETF/alert。registry适配risk_stocks→pure逻辑stocks并声明真实依赖，未污染其他family stocks；只有alert使用宽证券饱和集合。未知类型alert源不推测为股票，整体集合未证明完整。
- store风险组默认按合同日期轴：st pub_date，alert start_date，其他trade_date；schema/query/JSONL一致，显式date_field可查询实施/参考截至轴。未来imp/end、period、原因、原后缀source及历史T内部前缀保留。无st范围/offset；终端1000行仍blocked，单日发现fanout保留universe_unverified；所有历史/PIT/未知早史缺口保留。
- 439全Tushare tests通过13.115s，无skip，Ruff/diff-check通过。命令 UV_OFFLINE=1 uv run --no-project --with httpx --with pyarrow --with duckdb --with fastapi --with pyyaml --with reportlab --with pypdf python -B -m unittest discover -s scripts -p 'test_tushare*.py'；日志/tmp/tushare-risk-runtime-tests.log。
- 新7tests：29字段全链路/重复与异值来源、默认与显式日期及未来期限、T/ETF/历史source发现与计划依赖、不足历史与独立家族验证、缺列/参数fanout、4范围二分、实际1000行满额业务runner保持blocked。临时目录+mock transport/网络与凭据保护，无正式数据。父独立review后下一批发布/有限probe；当前采集持续，无需等DC全量回补。
