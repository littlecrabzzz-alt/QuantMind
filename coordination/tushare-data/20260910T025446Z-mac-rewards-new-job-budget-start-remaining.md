# 薪酬追加预算只计算新增任务

- 承接root生产actual624/planned524，当前append前500全部existing导致新增尾部100未到达。独立分支codex/tushare-rewards-new-job-budget基线a22f1079，仅改pipeline追加scope loop预算表达式、原append专项test及短doc；其他family规则不变。
- 验证624/524existing一轮新增100且done、全existing直接stream_end、>500new保持500新任务上限及断点、原time/scan仍有效。无生产操作、配置/任务写入或上游请求。
