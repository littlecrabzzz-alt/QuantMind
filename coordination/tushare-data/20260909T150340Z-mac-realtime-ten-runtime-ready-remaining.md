# realtime8 + replay2 runtime candidate ready

- Mac remaining_markets；base7b8a970；branch codex/tushare-realtime-runtime，commit99497d4（完整SHA见branch），已push、独立worktree clean。仅7文件：registry/pipeline/store/mirror、新专项test/doc、既有全storefixture必要身份/数量217→227。没有p_list/p_get公共接线；无production/配置/源probe/启用/重启。
- 关键分流：stk_auction运行态独立realtime_auction（enable_realtime_auction/realtime_auction_history_start），其余7 realtime_extra、2 realtime_replay，全部默认off。更换显式snapshotepoch不重置未完成竞价history游标；没有更改其他族policy。旧纯realtime_extra_apis若含auction须改用独立新scope，当前尚无该批生产配置。
- next_job后capture前新9API guard，使用实际dispatch时间+Asia/Shanghai：旧日/未来（含同日未来）/非法/未启用0HTTP，持久可审状态；保留tries/raw/attempts，新epoch不同ID可前进。竞价history和旧daily有/无guard对照的调用与job字节完全一致；没有修改next_job/tick/config读取/publish/通用history预算。
- 105字段含hidden及未知源列完整raw→normalize→fixedpublish→reader；五freq、各自独立daily API、IDX/FUND/FUT/CN及AUCTION_UNTYPED来源隔离；期货code/source_code及统一ts_code/source_ts_code。合法optional request dims以null保留，其余必填严格；期货/codefreq不符拒投影且原文保留。unknown时间不猜日期过滤。前日replay还无可信自动window来源，保留gap，仅current能计划。
- Python3.10全705tests/35.993s/OK；日志/tmp/tushare-realtime-runtime-full310.log SHAd325b25d7d6fdaf8d85bd2b6665e5d685e8c92899299e9acd3027e1be0d23cb4。最新专项9tests/0.964s含上海午夜边界和defaultoff；Ruff/diffcheck通过。既有微基准不推断生产提速。
- 父冲突接点：pipeline import、新族_planning_inputs keys、normalize/identifiers、prereq/validation、run发送前小块（约49行）；registry新块/PLANNERS；store新合同/optional/date；mirror复制清单。docs/tushare-realtime-runtime-intake.md完整接点/未验证项。候选不是已上线，父统一审查/发布。
