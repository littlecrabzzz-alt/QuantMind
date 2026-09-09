# Planning cadence 900秒：只读设计审查

- 基线：主master eed2c88（读取前后相同），Mac；未改代码/测试/配置，未访问云端、token或上游。只新增本coord。
- 结论：方向适合当前积压队列，**当前还不能直接生产启用**：主线尚无planning_interval实现和专项验收。可通过以下门槛后有界启用900，不需要等待全量回填。生产75s planning/69s identifiers/2.32M pending为父提供读数，本轮未重测，不能据此承诺加速倍数。

## 必须保持的路径和状态不变量

1. authority→ENABLED→非阻塞pipeline.lock→pending migration gate→锁内读config顺序不变（pipeline.py3044起）；busy/disabled/disk reserve/migration/非法参数不推进planning checkpoint。新参数必须type int、拒bool/float/负数，默认0严格保持旧行为，不悄悄切语义。
2. 新模式一个tick只做一个重阶段：publish到期优先返回publish_only；否则planning到期执行initialize+plan_extended返回planning_only；其余直接run acquire。**initialize899–984也是规划**（源记录扫描、全fund×quarter enqueue），不能留在acquire-only路径；否则只省了identifiers却没有完整隔离成本。轻量Pipeline打开/恢复/reconcile仍需分别计时。
3. 新cadence checkpoint独立于planning_state：不改任何已存anchor/signature/absolute offset/done/frozen identifiers、不改job identity/state/tries/result/raw/attempts。plan_extended1680–1853分family提交可保留部分进展；后续失败只是不写全局成功checkpoint，下轮从已提交offset继续。已有policy_changed/reset行为不能被cadence冒充迁移许可，尤其daily→month仍走journal协议。
4. 全局checkpoint只在initialize和全部plan_extended正常返回且规划提交成功后落盘；valid blocked-family gap可算“规划检查成功”，但报告必须明确blocked，不能称全scope计划已完。不要等archive/document/publish成功才定义规划成功。先commit后checkpoint写失败时允许下次幂等重做；checkpoint落盘后仅report写失败则允许重启跳过规划，不需要回滚已完成进展。
5. publish成功/失败/noop仅影响publish checkpoint，不推进planning；planning-only不打开provider HTTP client、不reserve API gate、不跑run、不inline下载或发布。生产publication与planning都900时会占相邻tick，属于显式约束，不能叠入一个160秒task。**publish_interval=0组合须先定义**：旧尾部publish不能重新叠到新planning-only或长acquire；最小可明确新cadence需正publication_interval，并拒绝不支持组合，而不是静默改变0默认。
6. 外层group_weights、每API公平/3:1、账户/接口/每日额度与错误冷却、单批requests/seconds都不变。独立documents由wrapper在tick前派发，planning/publish-only也不影响这一路；不能为省时取消文档消费者。

## 恢复、时钟、配置与触发边界

- 首次启用没有可信checkpoint：先尊重publish due，随后第一个可用tick必须规划，不把“当前时间”初始化为已成功。checkpoint应含模式/版本和锁内配置证据；损坏、负值/非整数不能被当成fresh。错误须可观察，不应偷偷延后900秒。
- 用跨重启wall-clock持久成功时间，用monotonic仅测执行耗时。elapsed<0（回拨）应强制一次检查而非无限等待；forward jump仅跑一次，不补发N个规划tick；边界elapsed==900到期。时间戳取成功完成后，下一次从完成时间算900秒，节拍与锁会另有延迟。
- **仅timestamp不足以处理config变化**：锁内new config与成功checkpoint的fingerprint不同，应立即计划或显式要求同锁失效；包括新增family/API、历史范围、种子、snapshot slot、批计划范围等。可用小型原子JSON保留fingerprint（scheduler_state.value声明INTEGER，不要隐式塞字符串）；或等价的可审查持久方案。fingerprint不能调用identifiers重新扫大数据才能判断due。该fingerprint只决定何时检查，不得替换family自己的policy/offset。rate-only配置变化允许一次多余规划；不能把配置变更当新历史epoch。
- 定时触发不是队列完成承诺：celery_config168–171每120s、expires110；acquire task soft160/hard180、acks_late/reject_on_worker_lost（tasks/tushare_tasks.py21起）。beat丢失/过期/worker退出后下一次成功取得锁只检查一次到期；重复投递由同锁+持久checkpoint抑制，不能累计补跑或手动调任务。若publish每个可用tick都到期或持续失败，优先级会使planning/acquire饿死，须报告starved，不把时间戳填新来掩盖。
- 900秒显著减少规划机会：500/family预算不变时理论每小时进度比每120s约少7.5倍（只比较理想触发数，非生产预测）；现有大pending可消费但新增品种/近期修订/缺依赖恢复发现延迟变长。reader实时snapshot TTL检查必须保留；如已启用的实时slot要求短于900，需明确它不能由本cadence保障，禁止伪造旧snapshot或以历史补采宣称未遗漏。午夜/小时epoch与6天catchup仍按原planner，不reset未完snapshot。

## 最小验收清单（候选未执行，不能当已通过）

A. 默认0与旧fixture逐路径等价；非法参数早拒绝。正interval首次、精确边界、重启、clock rollback/forward、缺/损坏checkpoint；busy不写；config锁内变化立即触发，普通相同config不反复触发。
B. publish与planning同时due只publish；下次规划；规划非due只acquire且initialize/identifiers/plan_extended零调用。发布失败不推进planning。planning-only无secret/HTTP/API gate预留/文档下载（wrapper文档独立派发不改）。验证positive planning与publish0支持或显式拒绝。
C. initialize异常、identifiers异常、family途中异常/SoftTimeLimitExceeded、最终commit失败、checkpoint写失败、checkpoint后report失败分别注入；复开真实临时SQLite，核对已有jobs/attempts哈希和各family旧offset不丢/不重置、不虚报成功。migration pending依旧拦截新旧路径。
D. 配置切换family/API/history范围与模式0↔900、同配置跨日、hourly文本、长时间beat缺失、重复投递/锁冲突；所有最近/历史source绝对offset保持，完成snapshot按原catchup推进。明确短TTL实时scope是否适配。
E. 现有test_tushare_publish_interval的9条（含60s publish+90s acquire不叠）和test_tushare_tick_timing、discovery_timing、history_budget、factor_month_migration、document_worker、公平/额度回归不得削弱。现主无planning专项。
F. 父受控启用后只观察至少planning_only成功1批、acquire_only成功2批、publish_only成功1批：模式/last_success/next_due/config fingerprint、stage耗时与实际HTTP attempts/rows；acquire不应仍有69s identifiers。planning批仍有soft160失败则不能只靠延长周期称解决；先回0兼容模式或按恢复策略处理，不删pending/覆盖DB。区分实际采集、发布、Mac镜像三个后续阶段。

建议：候选满足A–E、确认未启用短TTL实时自动scope后可试900；不提高预算、权重或源频次。F证明真实有效消费后再称生产验收完成。本次只读审查无生产启用授权动作。
