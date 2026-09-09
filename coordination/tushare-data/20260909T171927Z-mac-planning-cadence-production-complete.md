# Tushare规划分批：900秒生产验收完成

- 时间/节点：2026-09-09T17:19:27Z，Mac集成、云端authority部署。
- 主线：`f01f870` realtime probe工具、`5b488f3`跨日fixture、`aae3bc8`规划cadence；均已push master。双端4928文件digest `beae4b9dd83cc0b6ddd607fa3e909f13b9aacc05a9a3d6dad77e69362032813c`。
- 测试：规划专项9、发布10、时序5、完整Tushare 810项/45.944秒及Ruff通过。

配置只新增`planning_interval_seconds=900`，SHA `2600c2b5…`→`2ccb29fd…`；500rpm分层策略和900秒发布不变。采集consumer先停止接新任务、当前任务自然排空，再写不可覆盖prepared/committed收据并只重启tushare-worker。服务healthy、restart0、OOM0，队列已恢复消费。rollout helper SHA `70c48942…`，准备/提交收据SHA `5c42d771…`/`e18ed40e…`。

真实验收：首次planning-only `bf536d45…`总86.034秒、planning78.542/identifiers71.271、0请求并落检查点；publish-only `56ae4767…`总69.274秒并发布`data-0e961a88…`；两个成功acquire-only `4d3f9585…`/`3215f989…`分别44/95请求，run约89.94/89.98秒、任务总121.63/106.16秒，initialize/plan均未执行。启用后日志确认0个429/明确频率事件。验收文件`/data/tushare/validation/planning-cadence/900.acceptance.json` SHA `2ca27f7f8de77c98e383c43a68f4c8bad93cc18736892272930df734797242ad`。

限制：另一个acquire-only仍在acquire157.201秒后触发160秒soft limit，API冷却/响应/末次处理仍需继续拆解；本轮没有提高超时或资源。磁盘缓存普通cold/warm无收益且cgroup仍触1GiB，生产hold，安全候选`35bb612`留独立分支。900秒内新发现会延后，当前约235万pending可持续消费；短TTL实时范围启用前重审cadence。全量历史、修订、附件、PIT、9个未登记接口及RRG缺口仍继续，不能把本次吞吐验收当完整数据完成。
