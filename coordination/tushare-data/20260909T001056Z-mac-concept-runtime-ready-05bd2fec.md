# concept extra runtime 候选 ready
- Mac remaining_markets，codex/tushare-concept-runtime clean，基线 f2ef011；纯合同 e1041f2 的等价pick 0f80c5f，二者勿重复。
- 准确父集成顺序：e1041f2 → 03d8d74 → 55848e1；随后独立worktree完整审查/测试，再由父安排下一批短发布窗口。父当前 bbe2f9e 已恢复采集，本批尚未 probe / enable / deploy；注册候选不等于已采集。
- 03d8d74：registry/store/mirror、新 scripts/test_tushare_concept_extra_pipeline.py、152全合同fixture（DC真实请求身份）。55848e1：仅 pipeline 21增1删的独立 delta，prereq import/map/initial validation、ths_indices/dc_indices、opaque source normalization；父串行整合。未动主有限planner/publish/timing/limit文件/catalog/ledger/config，不启用、不联网采集、不访问生产。
- group concept_extra；enable_concept_extra 显式启用，concept_extra_apis、concept_extra_history_start（可每API配置，回退history_start）；ths_index一次无过滤snapshot，ths_member按存储ths_indices当前snapshot（不加history/is_new日期输入），ths_daily逐trade_date，dc_index逐trade_date+三idx_type。已有date_bisection适用两个日频API；THS/DC代码fanout仅证明发现的集合，不称完整。
- ths_index/daily/member原始观测ts_code并入ths_indices，dc_index原始观测ts_code并入dc_indices；不推入stocks/indexes。所有4API ts_code保持供应商原值（含股票外形与T历史外形）；member con_code、DC leading_code保留source字段，跨市场未知不得猜转换。store固定release读/代码筛选/JSONL同口径；DC保留三请求类别的同值来源行。
- 40 tests通过：concept pure8/runtime5、store_extended6、planning_progress14、limit runtime7；Ruff、diff-check通过。全是临时目录与mock transport，socket和凭据入口拒绝；依赖已有DuckDB deprecated fetch告警。
- 必留gap：全部权限unprobed；THS member最新成员不是历史/PIT，weight/in/out官方暂无、hidden四字段必须显式请求与验返回，5000仅本地guard非已知上限；没有完整跨市场成员发现，不造con_code fanout；THS master5000或单member饱和继续blocked；THS历史退市概念目录、DC分类返回/历史起点、旧修订/删除未证完整。未减少全目录义务，后续真实probe由父明确范围执行。
