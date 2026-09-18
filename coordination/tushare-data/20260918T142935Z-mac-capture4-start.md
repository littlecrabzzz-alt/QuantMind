# Mac Tushare 四路采集在线验收开始

- 时间、节点、任务：2026-09-18T14:29:35Z，Mac 全量归档所有者，capture4。
- 状态：开始有界代码候选；生产仍保持 depth 3 / process / 3 HTTP workers。
- 范围：只把采集 pipeline depth 和 process capture worker 的允许上限从 3 扩到 4，生产逐级从 3 调到 4；不改 500 次/分钟账户门、接口独立上限、每日配额、800 请求/100 秒批次、任务选择和原始证据写入。

最近普通生产轮次为 542、546、555、560、563 次请求，均无失败。最新一轮 563 次请求中，任务选择累计等待账户 gate 59.185 秒，563 次 capture 累计 69.280 秒，三路高水位为 3，说明网络/落盘仍占用接近三个并发槽。最近 5,000 条 attempt 全部 HTTP 200，状态为 2,668 `sample_ok`、2,326 `empty_unverified`、6 `possibly_truncated`，没有限流、传输、接口、权限或无效响应错误。

当前 worker 进程树抽样约 548 MiB RSS，系统 `Pages throttled=0`；第四个 capture 子进程预计只增加约 40–60 MiB。候选必须用本地 HTTP 夹具证明峰值恰为 4、所有请求一一完成、非法 5 路及 worker 大于 depth 仍拒绝。生产保留条件为真实周期提高请求数且无 429/配额推断、失败阶段、遗留 inflight、资源压力或文档吞吐显著退化；否则恢复三路。
