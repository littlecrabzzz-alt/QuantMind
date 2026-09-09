# projection上线首个指定真实任务

父确认99fb562/2295b84部署，仅重启acquire worker后，text_contracts按授权只做2次精确Redis GET：d7ac29bf-e042-496a-9e90-3b0b3dd068e0。Python-S、既有cloud-compose quantmind业务入口，仅取安全结果字段；无SCAN、数据库查询/写入、配置修改、任务派发、上游访问。两次read_at间隔58.85秒；第二次取得SUCCESS立即停止。

04:25:47.948796Z完成，184requests，总137.6670秒；acquire99.9004、planning28.0073、identifiers23.2265、initialize3.9024、document_registration4.3590秒。发现15003results/13934body_reads/2058bypass/0duplicate，planning和task均无failed_stage。

条件对照：上线前9038失败SoftTimeLimitExceeded，总160.0862秒，planning39.5482/identifiers34.1991；cf4成功220requests，planning33.1066/identifiers28.1916、acquire90.1667。新批发现时间较cf4少17.6%，planning少15.4%，但请求少、acquire更长，总时长没有下降；不同源规模、API组合及父可能进行自然锁空档配置/优先级工作，不是控制基准，不外推历史完成时间或总吞吐。0duplicate说明这次也不能归功于body去重。仅发现耗时方向与本地投影fixture一致，因果/稳定收益需后续普通批数据，未继续扩大观察。

证据 `/tmp/tushare-projection-task-after2-20260909.json` SHA256 `e34711bf79b09fc26333c7368eb1db04160ca814d0c87af6bac637c921b79566`。首次STARTED证据 `/tmp/tushare-projection-task-after1-20260909.json`。对照来自已有两份timing-live-second/third报告，未重查旧任务。
