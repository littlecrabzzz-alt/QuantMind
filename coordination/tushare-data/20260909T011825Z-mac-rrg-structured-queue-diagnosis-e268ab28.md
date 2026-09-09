# RRG 股票三接口仅一次采集的真实排队原因

- text_contracts，Mac通过既有 `ssh lzy-vm -> sudo bash /root/code/QuantMind/scripts/dual-node.sh cloud-compose exec -T quantmind` 业务入口只读。脚本只stdlib，SQLite URI mode=ro、PRAGMA query_only=ON、35秒读限，未实例化Pipeline、未读token、未写库/配置/停任务/调用Tushare。第二次小查询用python -S避免容器site启动钩子；首次容器启动钩子出现LiteLLM公共价格表拉取警告，与数据采集无关。
- 观察时间本地约20260909 09:15—09:16；任务持续运行，两个短只读查询不是冻结调度快照，计数随消费前进。

- `/tmp/tushare-rrg-structured-queue-state-20260909.json` SHA256 `403c55895814f6503cbaab9aa66bdeb3d2e92b9e80a9bd05e63cb651c689b08e`
- `/tmp/tushare-rrg-structured-queue-detail-20260909.json` SHA256 `2e704d436211014a3f5b3cd01e9cdf618f079fd3b3f6d4b64bf10c47d57b4897`
- `/tmp/tushare-rrg-three-api-probe-candidate-20260909.json` SHA256 `b3928239a7c56a2fe10c81507eabb1918517e6f775e5685e01c8f670049fc51d`

## 已证实

- enable_structured=True，26个选中API包含daily/adj_factor/daily_basic及6VIP；history_start19900101，plan_jobs_per_tick500。structured group_weight1，rrg3，其余启用family基本1；这三个股票接口实际group=structured，不会因rrg权重3而优先。
- 各API恰一次done、epoch probe-20260909-v3、trade_date20260908、tries1、priority-100；daily5549行，adj_factor5558行，daily_basic5549行，均sample_ok。能力表scope每日API前缀均available，checked_at20260908T17:20:46—48Z；只证明该次样本，不证明历史权限或完整覆盖。
- 三API每个20260902—20260908的7个recent任务均pending、priority25、tries0。当前不是反复失败/权限阻塞，而是没有轮到执行。
- daily历史13393日pending，19900101—20260901，priority45；adj_factor历史5098日pending，20120917—20260901；daily_basic历史尚未生成。无其余三API尝试记录。
- history:structured anchor20260909、offset33500、done0，policy2bf320cb69f90d4fc1b866240a89c22bf588ee0fe9ca1c7b38debda652248c90，signature SHA7887d86094c331abd7772efc7583bbf0c534b50abc772f1561b07d45953fa850。recent offset15009 done1；冻结发现stocks5909/indexes9662。

## 原因：计划与执行各有一个顺序瓶颈

1. structured planner先生成namechange全证券snapshot及其他reference，再recent，再按DAY_APIS逐接口整段历史（daily→adj_factor→daily_basic），日期倒序。33500偏移减15009近端前缀=18491，恰13393daily+5098adj。basic前仍约8295个adj日条目，500/tick约17次规划才能开始basic；这只估算枚举次数，不是到货ETA。
2. 真正消费者按family轮转，但同family `ORDER BY priority,rowid`，无API内公平。本次尚有634个namechange priority25在近期三API之前；第二查询队首已前进至688400.SH等，证实持续消费的是更早任务。其后index_daily仍8712个priority25以及其他reference/VIP任务，也优先于三API history45。单独增加structured权重，会先加速这些前置任务；修改history_start/API列表则会改变policy并重置规划快照，不应作为加速捷径。
3. 每日新增全量reference/指数近窗会再次形成长队，当前一天样本可用不代表持续回填。此项与注册合同或积分门槛无直接关系。

## 最小修复建议（只建议，未执行）

- 立即有界：仅提升已存在三API×7近日期21个pending任务到priority24，保留id/logical_key/epoch/tries/retry_after/result。现有enqueue为INSERT OR IGNORE，重复enqueue不会改已有priority；需经授权业务作业精确更新所选pending，不能重置整族。
- 随后3请求验证RRG预热起点20210517：daily、adj_factor、daily_basic无代码过滤，完整fields/row_cap见候选JSON。沿已有共享限流/原始留存执行，缺列/空/饱和/权限保留，不从已有积分推定结果。
- 研究窗20210517—20260831按已经核验的1286开市日，3API最多3858个日请求只是目标计划量，不是权限/完整性保证。先每轮不超过90个（最多30日×3）利用原Pipeline.enqueue、原history epoch及完整fields查存在则复用，缺才新建；仅提升已选pending，不清理旧任务/成果/attempts。当前basic尚未枚举，定向入相同identity后后续全量planner会幂等略过。
- 保持所有其他family份额不变。不能无限连续补高优先级而饿死同structured里的其他API；长程应由当前runtime owner审查API内轮转/有限研究窗口配额（例如研究占部分structured轮次，剩余仍原队列），避免改枚举顺序却沿旧offset造成遗漏。若只有配置/有限业务动作权限，先21+3的有限批，批后验收再决定后续，不凭升权重宣称问题已解决。
- 不动planning_state offset/signature、structured_apis、history_start或已有states。本轮没有实施以上修改；保持整体RRG blocked_data，成员known_at/历史分类与ETF门槛仍独立。
