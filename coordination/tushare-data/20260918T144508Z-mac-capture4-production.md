# Mac Tushare 四路采集生产结果

- 时间、节点、任务：2026-09-18T14:45:08Z，Mac 全量归档所有者，capture4。
- 状态：代码、测试、主分支合入、本地部署及五轮真实在线验收完成；四路配置保留，全量历史补采继续。
- 代码：候选 `2bcb017f`，主分支 `f90cedb6`。仓库与运行副本的 `tushare_pipeline.py` SHA-256 均为 `3677721aa4395db190517e55e8cbb17ca8c78a625fb48779cbd7ad2f63398990`。

代码只把 `acquisition_pipeline_depth` 和 process `acquisition_capture_workers` 的合法上限从 3 扩到 4。本地 HTTP 夹具证明峰值恰为 4、请求与持久化结果一一对应；5 路、线程并发以及 worker 超过 depth 继续拒绝。相关 73 项测试及 ruff、编译、diff 检查通过。

生产私有配置仅将 depth / capture workers 从 3 / 3 改为 4 / 4，SHA-256 从 `2491a46323e8c50fa91e82db372448310720d3dd242a88fcc5b5c790573a348b` 变为 `f13a9045c7e05263a20bf38ebf39b2b32815099079bb177d968cb401e4ec3616`。账户上限仍为 500 次/分钟，批次仍为 800 请求/100 秒，接口级上限、每日配额、任务选择和原始证据事务均未改变。部署先等待在途三路周期完整提交，没有中断或重放请求。

三路基线五轮为 542、534、556、563、560 次请求，中位数 556；四路五轮为 562、572、581、552、594，中位数 572。按各轮实际耗时和轮间固定 5 秒计算，预计请求吞吐从 17,243/小时提高到 18,229/小时，约提高 5.7%；文档阶段/小时变化约 -0.3%，无显著退化。

四路五轮的精确 attempt 范围为 rowid 726378–729238，共 2,861 次：1,586 `sample_ok`、1,272 `empty_unverified`、3 `possibly_truncated`，全部 HTTP 200；限流、网络、API、无效响应和权限错误均为 0。每轮 `http_workers=4`、队列高水位 4、`crash_recovered_jobs=0`、`failed_stage=null`。进程树抽样约 431 MiB RSS，系统空闲内存 85%，`Pages throttled=0`。

无凭据回执为 `validation/capture-workers-gray-v3.e9a44979db409ba283b2cb9e565f079ffbbdec52e4244ae0cefc803f050fb827.json`，文件名与内容 SHA-256 一致，权限 0600。没有 Token、订单信息或其他凭据写入 Git 或回执。
