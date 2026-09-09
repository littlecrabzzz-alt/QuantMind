# 开户历史2接口运行时完成

text_contracts / Mac / codex/tushare-account-history-runtime / commit662d7f4；父基线745e0a6含pure0d251f1。只本批registry/store/mirror、pipeline imports/normalize/plan_extended接线、新runtime tests/doc及授权store_extended215→217。records()/identifiers() AST对745e0a6完全相同，无缓存重叠。

account_history默认off；实际config key account_history_history_start与policy一致，只有月history，无近期source轮询。14字段/unknown/null/修订各API独立保留。旧date保留YYYYMMDD~MMDD，生成_period_start/end/status；本地默认闭区间相交，显式端点可筛选。unknown周期raw+完整Parquet仍留，结果period_projection_gap并走既有blocked；无日期完整读，as_of可见范围含unknown则日期查询明确拒绝。旧range上游轴未证，runtime不自动date分区，1000仅未验guard；无猜offset。新系列原周标签不伪造逐日/PIT。

验证：8runtime+9pure+fixedstore/API/融资/通用planning/historybudget共60 Python3.10 tests/2.988s/OK；Ruff/diffcheck通过。日志 /tmp/tushare-account-history-runtime-regression.log SHA 82689e5fda4e5b8bd03413b25db80f387a3cef2a85023426c1114a65dc72c4e1. 未按父要求重复完整638套；未source HTTP/生产配置/云写。完整边界见docs/tushare-account-history-runtime.md。

父仅pick662d7f4，不pick分支先前merge；后续真实权限、旧周查询过滤语义及云/Mac固定验收仍由父组织，默认关闭不变。
