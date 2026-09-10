# Tushare `eco_cal` 单日饱和后代接线

状态：已部署并完成生产恢复验收，代码版本 `66df93ba78268cf915a36d590bf83390f4db457f`。离线候选阶段没有访问 Tushare、读取凭据或修改生产数据和配置。

`eco_cal` 的无国家条件单日请求达到 100 行警戒线后，原始响应先按既有协议落盘。运行器随后仅从本地已保存的 `eco_cal` 任务和尝试结果提取原样 `country` 值，为同一个 `date` 生成 `country+date` 后代。空值、首尾空白、控制字符和超过 128 字符的值只保留在原始响应中，不进入请求参数；合法值允许内部空格，不改写来源文本。

后代继续使用既有 `enqueue` 身份：API、请求内容和 epoch 相同就得到同一任务 ID。后代属于原 `calendar_extra` 队列，继续经过账户/API 分层限速、已观察冷却、优先级和公平调度；本接线没有增加专属请求入口或提高频率。

每次本地恢复最多新增 `min(plan_jobs_per_tick, 100)` 个后代。未完成的观察值保留 `partition_deferred`，可在进程重启后继续，已经存在的后代不占本轮新增预算。旧版留下的 `blocked + possibly_truncated` 父任务只在原始对象和观察记录仍存在时原地恢复，不重发 HTTP。

国家观察集合仅用于运行期饱和拆分，不进入 `calendar_extra` 父规划合同和签名，因此新增国家不会重置 recent/history 游标。父分区始终保留 `coverage_proven=0` 和 `universe_unverified`；观察到的国家不代表历史国家全集。若某个 `country+date` 后代仍饱和，它保持阻塞，因为货币、事件和更细分页全集没有得到验证。

离线验收覆盖来源隔离、内部空格、旧父任务恢复、一次 HTTP 后分轮生成、跨进程续跑、稳定任务 ID、原始对象引用、父游标连续、`coverage_unverified`、同队列限速合同和通用分区回归。生产镜像断网专项 29 项通过，完整 Tushare 回归 989 项通过。

生产常规调度已从两个各 100 行的旧 `blocked` 父任务恢复拆分，没有重发父请求；原 object/observation 引用和父尝试次数保持不变。每个父任务连接 24 个从不可变 `eco_cal` 结果观察到的原样字段值，其中本父响应包含 18 个，另 6 个来自此前保存的 `eco_cal` 结果。Tushare 原始 `country` 字段同时出现国家名和分类标识，运行器不凭名称删除来源值；后代的真实空结果继续保存为 `empty_unverified`。

不可覆盖阶段快照保存在 `/data/tushare/validation/eco-cal-saturation-20260910/acceptance-20260910T145651Z.json`，SHA256 `15e3c6bd0cfc8bfd278547dab7b9dc36f0ce0a4bc0c224d9d2973edaa560a79b`。随后 `calendar_extra` 常规队列按既有限速和公平调度自然处理完全部 48 个唯一后代：24 `done`、24 `empty_unverified`，48 次请求全部 HTTP 200，每个后代只尝试一次。最终闭包收据 `/data/tushare/validation/eco-cal-saturation-20260910/closure-20260910T150820Z.json` 的 SHA256 为 `31499010eb699b440b69f48831c383197c092da710138db7e68d4d110bf3ade4`。两个父分区仍为 `coverage_proven=0 / universe_unverified`，因此后代处理完毕不等于供应商国家或分类全集已证明。
