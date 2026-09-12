# cyq_chips 每日配额范围只读审计

- 时间：2026-09-12T07:11:00Z（Asia/Shanghai 15:11）
- 状态：结论完成；仅建议，未实施代码、配置或服务变更。
- 边界：读取官方 doc294/doc290、当前源码、既有归档，以及一次按主键限定的云端只读 gate/配额小账本快照；未读取凭据、未调用 Tushare、未扫描 jobs/attempts、未修改 authority 或服务。云端 SQLite 连接均在 fetchall/fetchone 后关闭。
- 云端代码：`4911af05ffbe1d537709fed35a6def1fbb18f27d`。

## 权威范围

- `cyq_chips` 详情页 `https://tushare.pro/document/2?doc_id=294`：单次最多 6000 行；5000 分每日 20000 次，并在该档文字中明确每分钟 200 次；10000 分每日 200000 次；15000 分每日不限总量。输入必须有 `ts_code`，可配 `trade_date` 或日期范围。
- 通用频次页 `https://tushare.pro/document/1?doc_id=290`：10000 分以上常规接口 500 rpm，特色数据 300 rpm；15000 分以上特色数据总量不限。
- 两页对 10100 分档的分钟频次存在表述边界：详情页没有把 200 rpm 明确重复到 10000 档，而通用表给特色数据 300 rpm。当前实现取 200 rpm 是安全的保守上限，不应提到 300，除非新证据明确详情页在该档的分钟规则。
- 当前 10100 分使 `cyq_chips` 每日上限为 200000；2026-12-05 起 2000 分 tranche 到期后预计 8100 分，仍满足调用门槛，但每日上限应降为 20000。积分只说明门槛；现有真实 `sample_ok` capability 才是当前账户可调用的运行证据。

## 当前实现与生产基线

- `backend/shared/tushare_intake.py:capture_sample` 在构造 HTTP 之前调用 `tushare_daily_quota.reserve(root, api)`；本地 request-contract validator 更早执行，因此无效请求不消耗日额度。
- `backend/shared/tushare_daily_quota.py` 使用单独 `daily-quota.sqlite`、北京时间自然日、`BEGIN IMMEDIATE` 和 `(api, day)` 主键；预留先于 HTTP 提交，传输失败和不确定中断不退还，损坏/时钟回拨失败关闭。账本只覆盖该 authority root 内经过 `capture_sample` 的调用，不能称为供应商全账户用量。
- 实际缺口是 `reserve` 第13行只允许 `cyq_perf`；表结构已经按 API 分区，不需要新增数据库或扫描 authority。
- 2026-09-12T07:08Z 只读快照：配置 `tiered_v1`，账户 ceiling/rollout 均 500 rpm；`cyq_chips` 由详情页 override 解析为 200 rpm，`cyq_perf` 为 300 rpm。`cyq_perf` activation day 为 2026-09-10，账本 2026-09-11=176、2026-09-12=92；`cyq_chips` 无 activation、无 counter，因此其日总量当前未受本地硬账本保护。
- 同一快照中 `cyq_chips:` 和 `cyq_perf:` capability 均为 `available/sample_ok`；不存在 `quota:cyq_chips` 或 `quota:cyq_perf` 的供应商实测速率 cooldown。瞬时 request gates 为 account=15:08:42、cyq_chips=15:07:24、cyq_perf=15:07:30 CST，均已在15:09:20观测时过期；这些只是每次请求前的短间隔预约，不是日配额。
- 既有归档只证明当日部分 `cyq_chips` 调用；因为此前没有该 API 的硬账本，不能从 attempts、当前 retained objects 或“未见记录”推导同日供应商全账户使用量，更不能初始化为0。

## 唯一建议

需要扩展 `cyq_chips`，但不要新建配额系统。最小安全改动是复用现有按 API 的账本：

1. 将受保护 API 从单个 `cyq_perf` 扩为不可变集合 `{cyq_perf, cyq_chips}`；两者继续使用相同积分档函数，但计数、activation、状态必须按 API 独立。
2. 部署当天为 `cyq_chips` 建 activation day，并保持现有 `day <= activation_day` guard：当天任何首次选择只设置该 API 的 retry gate 到次日北京时间零点，`upstream_calls=0`，不写 attempt/result/tries。不要用当天 retained attempts 回填一个较小数字；它不能覆盖进程中断、旁路客户端或供应商账户其他使用者。
3. 次日才从0开始，因为本 root 在 activation day 已被硬阻断。若业务要求同日继续，则安全值只能是 fail-closed（视为当日已耗尽），除非取得供应商账户级、可核验的当日用量；不可用估算下界作为余额。
4. 将 `status` 和 `policy_report` 扩为每 API 状态/limit/used/remaining，同时暂时保留现有 `cyq_perf_daily_cap` 字段以免旧归档消费者断裂；明确 scope 仍是 `this_root_capture_sample_only`。
5. 不改变账户 500 rpm、`cyq_chips` 200 rpm、`cyq_perf` 300 rpm、现有 observed gate 合并、失败不退款、账本不发布/不镜像等不变量。

必须有的最小测试：两 API 首日分别 guard；次日分别计数且互不占用；并发最后一格只有一个成功；2026-12-05 后 limit 从200000降到20000；`cyq_chips` guard 时 HTTP/attempt/result/tries 为零且其他 API 可继续；账本损坏、时钟回拨、传输失败及非保护 API 行为不回归；status 未激活时 `used=None`，不得显示0。

## 不能声称

- 本地计数不是 Tushare 全账户余量，也不覆盖其他机器、手工脚本或绕过 `capture_sample` 的客户端。
- `available/sample_ok` 不证明每日额度或分钟频次经过压测；200 rpm 是保守合同值。
- 日额度保护不会证明历史完整、PIT、修订覆盖或 RRG 可用性。
