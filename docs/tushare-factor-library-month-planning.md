# 因子值历史月窗口候选

新增显式 `factor_library_history_window: "month"`，只接受 `factor_library_value_mode: "code_only"`。省略或设为 `"daily"` 均保持现有按日请求和有效 policy 字节不变；默认名称模式仍照旧按日。没有修改默认启用范围、供应商参数、四个字段、6000 行阈值或证券发现。这里只交候选，不启用、不迁移生产队列。

```json
{
  "enable_factor_library": true,
  "factor_library_apis": ["factor_value"],
  "factor_library_value_mode": "code_only",
  "factor_library_history_window": "month",
  "factor_library_history_start": "19900101"
}
```

这是目标配置示意，不能直接写到存在未完成日游标的运行环境。`factor_library_history_window` 只有非默认值进入 `_planning_inputs`；部署候选本身不会改变缺省配置的旧签名。contract 字典保持原样，避免因为新增说明元数据而意外改变签名。

## 分区与已验证范围

对于冻结 anchor，近期是 `[max(history_start, anchor-6天), anchor]`，仍用每日 `trade_date + ts_code`，优先级20。历史是 `[history_start, anchor-7天]`，用已有 `_months` 裁切自然月的 `start_date + end_date + ts_code`，优先级55、epoch仍为 `history`。边界不足一月仍全部保留，不按自然周或交易日猜测删日。每个实际源代码独立枚举，`T600018.SH` 等历史身份不变，不依赖 `factor_list` 或猜测因子名称。

在同一冻结 anchor 内，两部分无日期重叠、无洞；这里指逻辑请求覆盖，不证明供应商每天有数据。完整旧月端点稳定，首月尊重配置起点，尾月尊重近期边界。既有冻结发现/anchor 的恢复逻辑沿用，不能把新枚举套到旧日 offset。

本次只读复用 `/tmp/factor-month-{cloud,mac}-fixed.json`：固定
`data-4d55e6bd73c9aae57feaa5623518c01984c5338b7b00398887be4d21f8880249`，
probe SHA `0f08f3f950accdf373de33102df6f7ea0bf172e82371b749ace0631af6548fab`。
`000001.SZ` 的2026年8月有4340行、21个日期；0817对照212行，原文四列及两个节点固定 reader 对账一致。这只证明这个样本窗口，不证明所有股票月份不饱和、目录完整或PIT。

本地纯生成器、anchor20260909、每一个股票的实际计划计数：

| 请求范围 | 原历史日请求 | 月历史请求 | 近期日请求（均不变） |
| --- | ---: | ---: | ---: |
| 19900101起 | 13394 | 441 | 7 |
| 20260801起 | 33 | 2 | 7 |

长范围初始历史计划减少约96.7%。这是请求计划数量，不是线上耗时或总采集量预测；发生饱和的月份还需拆分。达到6000时继续现有合法日期二分，保留全部原文及父子状态；一个代码一天仍饱和、空、缺字段或权限不足时保持缺口，不能用“月已请求”认证完成。因子目录、资产映射、公式、历史修订和发布时间仍未证明。

## 后续迁移设计（本提交不执行）

现有通用 `plan_extended` 遇到 policy 变化会重建 `planning_state`，包括未完成的状态。因此直接改月配置虽会从新流的0开始，却会丢失旧流的继续规划位置；不能作为安全迁移。必须由单独经过测试的有界迁移 helper 在共享锁内处理：

1. 保存审计前像：完整旧配置及SHA、`recent:factor_library` 与 `history:factor_library` 的 anchor/signature/offset/done、冻结 identifiers/epoch，以及受影响确切 job ID、job内容、state、tries、result、priority、retry_after。保留只读可恢复的旧游标副本和旧日义务范围；原记录、raw/observation/Parquet/attempt 不删除、不改写。
2. 在纯规划层证明转换：使用**旧冻结股票集合、起点及 anchor**，对旧历史 `[start,anchor-7天]` 建立代码×区间的月覆盖证明。每个区间起止连续，相邻端点差一天；输出区间证明摘要及SHA，不需要物化千万个日期。旧游标尚未枚举的尾部也在证明范围内。旧近期义务保持原队列，不移作历史；新股票和新 anchor 待独立策略接续。
3. 在所有旧游标及配置前像仍匹配时，原子保存旧日检查点与迁移映射，再创建从0开始的月规划状态。新 policy 和新 offset 属于新流，绝不复用旧日 offset。需要对开始前/中途崩溃、重复执行、同时新增发现进行故障注入；如无法原子保存与切换则整次拒绝。这里没有新增运行时迁移代码或宣布可以直接操作。
4. 已有日任务可继续消费。若为减少重复而采用可逆 deferred 状态，必须使用逐 job ID 审计映射保留原值，并证明其日期、代码落在对应新月范围。**仅新月已入队不足以放弃旧义务**：月任务失败、空/缺字段、权限不足、饱和未闭合时，旧日义务仍为未解决并可恢复。只有来源/字段/过滤及完整子分区闭包验证通过后，才可按明确覆盖规则处理对应待执行日任务；done、已有尝试及正在执行的任务不做替换。
5. 回滚不能恢复旧整库覆盖新增进度。按迁移审计精确撤回仍符合前像的配置/状态；保留新月已经取得的原文/尝试。恢复旧冻结日游标继续枚举，已存在 logical key 由现有 enqueue 幂等复用。迁移清单随完成状态登记，不能把归档旧游标或 deferred 数量当作数据完成。

需要的迁移验收：旧非零 offset、在近期前缀内/历史中、不同冻结发现、部分月份饱和嵌套、失败/空/月成功后故障、审计中断重跑、回滚后旧任务新增进度不丢，以及所有原 job/attempt/raw SHA 不变。必须先证明义务和恢复，再做生产切换。

## 可复跑的只读迁移预检

新增 `scripts/tushare_factor_month_migration.py`，当前**只有 plan-only，没有 execute/apply/rollback 开关**。源码确认有两个阻碍：`pipeline-config.json` 的文件 replace 与 SQLite 不共用事务；`tick()` 还在取得 `pipeline.lock` 前读取配置。仅在 helper 内加共享锁，并不能阻止已拿到旧配置的 worker 对新状态再次按日 policy 重建。这个提交不越过该边界，不把“先写一份、再写另一份”称作原子迁移。

预检使用现有非阻塞 `pipeline.lock` 和 `mode=ro/query_only`，仅按主键读取两个因子检查点，无 jobs/attempts 扫描。不构造 Pipeline、不读取凭据或网络、不改配置/状态/数据。整个 CLI 硬限30秒；状态不是schema6、旧签名未知、配置与冻结 policy 不同、发现不足、offset超出旧流或月规划未安装时拒绝。应在已经安装本月规划候选的代码路径下运行：

```sh
python3 -S scripts/tushare_factor_month_migration.py \
  --root /data/tushare --output /tmp/factor-month-migration-preflight.json
```

输出在权威数据目录外，包含完整 config 字节SHA（不复制配置内容/凭据）、两个检查点精确前像及SHA、源代码SHA、冻结代码和月区间覆盖证明、旧流绝对offset位置及尚未枚举日尾部数量。用一只实际冻结代码调用当前纯月 planner 核对全部窗口，余下代码遵循同一笛卡尔积。候选状态只写进审计文件：历史新流建议从0开始；近期流不变、只建议更新policy，不直接迁移其offset。证明覆盖全部旧历史请求义务，不认证已取得数据。

审计文件原子、不可覆盖；同一前像重复生成内容相同。已有审计的复验必须同时提供文件SHA：

```sh
python3 -S scripts/tushare_factor_month_migration.py \
  --root /data/tushare --output /tmp/factor-month-migration-preflight.json \
  --revalidate /tmp/factor-month-migration-preflight.json \
  --expected-audit-sha256 REVIEWED_AUDIT_SHA256
```

配置、任一规划游标/冻结发现或候选源码变化均拒绝复验，不恢复旧值。普通旧日任务在此期间完成、增加原文/attempt时不会被回滚；本 helper 从来不改这些行，也不批量 deferred。审计写入前/原子安装后崩溃不影响权威数据，重跑复用完整审计。`apply_allowed=false` 和两个阻塞原因始终保留。真正切换需要后续单独审查运行时协议（至少锁内读取配置，以及worker可识别、可恢复的配置/游标切换提交点），不能仅凭这份预检直接操作。
