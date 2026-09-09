# 融资历史3接口纯合同完成

text_contracts / Mac / codex/tushare-securities-lending-history / commit34647a8（基线合入master5d442d3）。只新增合同与专属tests两文件，无registry/pipeline/store/config变更。接续070550Z。

slb_sec/slb_sec_detail/slb_len_mm共20完整knownfields、隐藏0、未知列/空值原样capture；明细tenor+fee_rate自然键和内容版本保留。文档5000cap实际未验、共享上限30rpm；停更/起止/权限/PIT未知保留，不与slb_len合并。显式enable_securities_lending_history=true才有规划，securities_lending_history_apis/history_start可限定；默认19900101仅请求边界。近7日priority20再历史40，日期×API轮转，不硬筛周末/退市。饱和复用日期二分+stocks真实code，单code/day无合法继续分割仍gap。

Python3.10：8专项+credit_extra/field_coverage相关共25tests通过0.031s；Ruff、diffcheck通过。测试含完整cataloghash/字段、disabled、闰年/周末/稳定history键、近期优先、未知下界、T退市身份、不全universe、generic date_children、不丢null/zero/unknown、missingnullable schema_gap、5000cap/empty。无源HTTP/生产/云写。

父仅pick34647a8，不pick本分支历史merge。集成点：新family及纯planner、_planning_inputs keys(enable由既有外层管理、apis/history_start)与stocks饱和依赖；合适的normalize/store保留source代码与_row_identity及trade_date；mirror复制模块；有限真实历史probe后再启用。运行模块由父另行安排，本候选不代替真实权限/固定release验收。
