# Mac Tushare 采集完成顺序调度生产结果

- 时间、节点、任务：2026-09-18T15:01:45Z，Mac 全量归档所有者，capture-completion-order。
- 状态：代码、测试、主分支合入、本地部署及五轮真实在线验收完成；候选保留，全量历史补采继续。
- 代码：候选 `45790d39`，主分支 `036cd428`。仓库与运行副本的 `tushare_pipeline.py` SHA-256 均为 `ab23d92df9cd9d7f7691a1fce72b52e4e50db1cadaf3fe3b156bea4df2b4c155`。

原四路实现按提交顺序等待队头 future，慢请求会阻止已完成响应提交和空闲槽补入。新实现等待任一 future 完成，先提交实际已完成的 response，再补入下一条已合法预留的请求。账户/API gate 仍在派发前由主进程持久化，attempt/job 事务仍由主进程逐条提交；worker、depth、500 rpm、800 请求/100 秒、每日配额及任务范围均未改变。

慢队头 HTTP 夹具证明：第一个响应未结束时，第二个响应先完成并触发第三个请求使用空闲槽；三条任务各提交一次、终态均为 done、遗留 inflight 为 0。相关 74 项测试和 ruff、编译、diff 检查通过。

部署前四路五轮为 593、560、584、594、552 次请求，中位数 584；部署后五轮为 751、721、777、758、757，中位数 757。按轮次实际耗时和固定 5 秒间隔计算，请求吞吐从约 18,405/小时提高到 24,900/小时，约提高 35.3%；文档阶段/小时提高约 5.2%。五轮均报告 `completion_order=first_completed`、`http_workers=4`、高水位 4、`crash_recovered_jobs=0`、`failed_stage=null`。

候选五轮精确 attempt 范围为 rowid 731017–734780，共 3,764 次：1,787 `sample_ok`、1,969 `empty_unverified`、8 `possibly_truncated`，全部 HTTP 200；限流、网络、API、无效响应和权限错误均为 0。进程树抽样约 418 MiB RSS，系统空闲内存 85%，`Pages throttled=0`，数据卷剩余约 2.31 TB。

无凭据回执为 `validation/capture-completion-order-v1.638f44de446dbfa27038a3611f6bd830d6ab2f673575b6da6d85997ca582dfb3.json`，文件名与内容 SHA-256 一致，权限 0600。没有 Token、订单信息或其他凭据写入 Git 或回执。
