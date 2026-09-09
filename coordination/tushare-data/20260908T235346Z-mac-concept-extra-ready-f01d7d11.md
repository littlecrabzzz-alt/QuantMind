# THS/DC4纯合同候选交接
- remaining_markets Mac codex/tushare-concept-extra；增量e1041f2762992d415ddab48e79f292a0d4259ae3，基线91fc460。不重复limit运行merge；只新增concept_extra合同/tests/doc三文件，无runtime/生产访问。
- 对比263+13、正式144+limit4，选ths_index259/ths_daily260/ths_member261/dc_index362；40输出/全部输入与目录一致，所有权限unprobed。
- ths_daily隐藏total_mv/float_mv；member隐藏weight/in_date/out_date/is_new，前三官方暂无；均显式required+nullable，返回整列缺失仍gap。member只最新成分，单次cap未公布：5000仅本地保护阈值,row_cap_verified=false，不能由未触阈值宣告完整。
- ths_index遵从一次全量勿循环，每epoch一无筛选快照，无3市场×7类型grid；member仅对ths_indices存储发现逐code快照(真实planner dependency)。daily/DC最近7日+配置history惰性轮转，全部未知历史起点不猜下界。
- DC显式idx_type行业/概念/地域3类（table必填与sample省略差异保留），request_identity_fields=[idx_type]，父将来store全合同fixture须真实请求身份。两供应商各自namespace；成员跨A/HK/US和leading_code格式待实证，禁止自动塞入A股。
- export CONCEPT_EXTRA_CONTRACTS/iter_concept_extra_jobs/concept_extra_prerequisites；future group concept_extra，concept_extra_apis/concept_extra_history_start回退history_start。member依赖ths_indices；daily/DC饱和ths_indices/dc_indices，未实现runtime discovery/fanout。
- 8纯离线tests、Ruff、diff-check过；成员历史PIT/旧修订/退役板块/未公开cap全部gap，RRG整体阻塞不解除，目录义务不删。
