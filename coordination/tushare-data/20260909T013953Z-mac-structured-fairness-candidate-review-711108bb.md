# structured长期饥饿：只读候选方案

text_contracts/Mac；本轮只读当前pipeline/structured planner/beat配置和已保存两份09:15队列读数，未再次访问云端、未改runtime/配置/范围。关联：20260909T011825Z-mac-rrg-structured-queue-diagnosis-e268ab28.md；临时21+90提级是父独立执行，本报告不宣称它已完成。

## 证实与假设

- 已证实：组外按权重轮转，组内priority,rowid，无API公平；structured权重1、18个实际采集family总权重20（documents不计入PLANNERS，rrg权重3）。三股票API近7日都已排队tries0，namechange队首尚约634；index_daily近端8712排在history45前。history planner按DAY_APIS整段排，offset33500=前缀15009+daily13393+adj5098，daily_basic尚未枚举。这些是请求次序事实，不是权限问题。
- 当前recent一次完整anchor枚举15009项，其中namechange5909+index_daily8712=14621。新anchor会保留旧任务并加入新epoch/日期窗，不能当它们已采完或可覆盖旧观察。
- 容量仅条件估计：240账户rpm、120秒beat、每批90秒acquire、全组都有可执行任务且份额近1/20，则structured理想12960尝试/日，已小于15009近端项；若全天连续采集则17280/日。实际受其他组空闲fallback、API冷却、失败重试、批间开销/锁、publish间隔影响。本轮没有全天增量，不能据此宣布永久不收敛，也不能保证调整后每日及时完成。

## 三种措施比较

|措施|改善|不足|
|---|---|---|
|21近窗+90研究窗一次提级24|最小确定性推进，保持全部旧任务/游标，可先验证RRG起点|有限批后仍恢复旧顺序；无限补高优先级会挤压其它structured API；不是长期修复|
|structured内部按API轮转|名称变更/全部指数不会垄断同组；不改变其他family权重|同一个API仍按近期25先于历史45，日增近期若过量，该API历史仍可饿死|
|API轮转+各API有限近期/历史配额|即使持续有recent，history也能获得明确服务机会|不能创造总容量；近期等待可能变长，不能承诺新鲜度SLA。空/冷却API必须跳过，不可为等配额空转|

## 最小推荐候选（分两步，不改当前枚举顺序）

1. 下一轮先只改`Pipeline.next_job`中选中structured后的候选查找，外层family_turn/group_weights/account/API request_gates及其他组fallback保持。从已有registered structured API（含保留的旧别名任务）按稳定顺序轮转，有ready任务才选；若所有structured API无ready任务，保持原跨组fallback。未知API不能静默丢弃，应明确gap。
2. 对每个被选API使用独立3recent:1history计数；history严格epoch='history'，其余已存在epoch仍可服务，桶内保留priority,rowid。某桶无ready则借另一桶，两桶都冷却则跳API。计数在成功保留request gate时与family_turn同事务提交，失败请求也消耗该次服务机会，与既有公平语义一致。**不要用一个全局%4相位与API轮转组合**：API数为4的倍数会让某API永久落同一相位；必须每API相位。3:1仅首候选，需离线负载验证后审查，不是生产定值。

持久状态可复用scheduler_state新增`structured_api_turn`及`structured_phase_turn:<api>`整数项，不改job id/logical_key/epoch/job JSON/tries/result/state。为避免每请求扫描大组，候选schema v6只加一个pending表达式索引：`jobs(group_name,json_extract(job,'$.api_name'),(epoch='history'),priority) WHERE state='pending'`，使用明确相同表达式过滤，rowid自然尾序。先对合成大队列EXPLAIN/耗时确认索引收益及创建锁时长；v5→v6保留全部行，旧代码拒绝v6需部署/回退兼容准备。若实际旧索引已足够才可免此迁移，不能未经测量声称无需索引。

## 历史planner不要顺手重排

本轮basic前约8295条，500/tick约17次规划即开始（不是到货ETA），且父有限研究窗可提前幂等补入basic，故上述消费公平候选可以不改纯planner，范围最小。

若后续确需历史DAY_APIS逐日跨API轮转：旧offset是旧序列的位置，直接改generator后沿用offset会漏任务；清零会重复巨大前缀并挤占队列。应让未完成snapshot明确继续legacy枚举直到done，新snapshot持久`enumeration_version`再切v2；旧缺版本默认legacy，不能因新版本字段改变policy而重置旧快照。每个产出的params/fields/epoch仍与旧版一致，已有logical job通过INSERT OR IGNORE复用。这里只列后续方案，不为这一轮吞吐修复引入第二套planner。

## 最小验证与补充读数

- 连续插入namechange/index recent，断言其他ready API有界被选，且每API同时有两桶时history每4次机会至少1次；API冷却/只有一桶/重试负优先级/进程重启均覆盖；26/28/32种API数防相位共振。
- 对照outer family服务序列、共享gate间隔与旧job全字段哈希；只允许新增scheduler计数/索引，不能删除pending/empty/失败/历史观察。v5迁移中断恢复、重复迁移及大队列EXPLAIN/选择耗时测试。
- 后续用两个有时间间隔的只读统计点（建议跨一个完整anchor日）记录各API/桶新增、attempt、成功/空/饱和/权限、最老pending日期与等待时长、分组实际服务份额和acquire有效秒数。区分规划done与采集done；依据真实增量判断容量与新鲜度，不为了看起来清队列降低历史范围/删旧epoch。
