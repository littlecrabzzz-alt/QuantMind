# Publish 热点有界只读评估（非本轮发布阻塞）

父 b849e87 publish 源码只读；remaining owns tick。仅现有 cloud-compose business exec，quantmind 容器 SQLite mode=ro/query_only；无显式长读事务、单SQL2–4秒进度中断，第一轮总3.66秒、第二轮总1.61秒。仅摘要到Mac，无原始数据迁出，无生产写/索引/发布/暂停/上游调用。本轮无runtime候选commit。

## 已测量

当前schema5，951,706 jobs：pending877,624、done36,116、empty25,368、deferred_legacy_period_plan9,802、permission_blocked1,164、split_pending999、resolved364、blocked193、quality76。实际gaps37,602，不能只白名单常见state；attempts63,800、partition children335,346、splits1,363。scan_gaps、coverage、scope均全jobs扫描；后两者临时GROUP/DISTINCT排序。status走既有jobs_pending覆盖索引，0.19秒。

- 前3000 gap样本：原SELECT*+job双json.loads 50.9ms；窄列+job单解码46.4ms；JSON SQL投影30.7ms；输出SHA一致。该样本只显示单解码有限收益，不能解释生产12.50秒全部耗时。
- rowid<=100000：25,469 gap原395.4ms，动态发现所有非done/pending/resolved状态并强制jobs_pending索引398.3ms，输出SHA相同但未证明收益。新计划避免宽表全扫、另做state覆盖索引扫描+rowid排序；没有执行95万行宽表全量新旧对比，不建议现在盲加hint/索引。
- 同10万rowid覆盖GROUP 237.8ms，scope重复扫描211.4ms。由覆盖列表派生scope的97 API顺序及SHA与现有DISTINCT ORDER BY相同；强制jobs_partition_lookup的scope反而216.8ms，无收益。
- 当前已存固定manifest data-ea8b819290385b2d630d940e2e3bd041f0c51ae59fe62c1256ba7ea4c9ff5af3，75,477,037B，SHA通过。quantmind重新json.dumps(sort_keys=True,ensure_ascii=False).encode耗时0.87秒，与现存文件逐字节相同；不是发布调用。files32.79MB、partition_closure23.16MB、datasets8.70MB、gaps7.84MB、planning2.77MB；全部必须保留。

## 容器差异与归因边界

quantmind cpu.max=300000/100000（3核）、memory.max12GiB；tushare-worker=75000/100000（0.75核）、memory.max1GiB。读取时worker memory.current572,125,184B，累计memory.events max70,310、oom/oom_kill均0；cpu累计nr_throttled9,015。以上是累计计数，不能归因到某一次publish；JSON单线程也不能按3/0.75简单线性换算。serialize阶段源码只有一次json_bytes(content)+一次SHA，并无重复整清单序列化。生产15.81秒softlimit中断与quantmind0.87秒不是同cgroup/同候选，资源约束、候选体积、缓存状况仍需worker阶段测量才能区分。

## 下一轮最小候选（不修改tick/格式/历史）

1. 优先在publish内先执行一次现有coverage_by_api GROUP查询，明确ORDER BY api_name,state；由它求和构造coverage，并按已排好序API去重生成scope。删除status/scope两次重复查询，仍包含所有未知state/API。48行临时SQLite夹具含未来API/未知state，三个输出整体canonical JSON字节相等；10万范围真实scope亦SHA相等。建议再用父完整manifest/闭包回归逐字节验收，避免误改list顺序。
2. serialize_manifest之前、最后一次preserve_release_mapping/retain/archive_inventory完成后，释放局部previous引用（previous=None）。此后源码不再读取previous，只用previous_id；无manifest字段变化，可减少上一版datasets/gaps/planning与旧files容器的同时驻留。预计有利于1GiB worker峰值，但释放量/耗时未在worker测量，CPython释放不保证RSS立即回落。先在临时fixture确认所有输出字节/失败CURRENT/继承闭包等价。
3. scan_gaps可先窄投影id/state/job/result、job只json.loads一次，保留原行顺序与所有未知state；没有理由为了小收益改变NaN/重复key等Python/SQLite JSON处理语义。将resolved在SQL提前排除虽不改变manifest，但会略改变原无用result解码校验行为，建议最小版仍保留该路径。动态state索引方案留待同cgroup、有界代表性区间证据，不新增schema7。

不建议本轮换JSON encoder、压缩/分块manifest、缩字段、丢attempt/revision/closure。json.dumps再encode会同时占用字符串与bytes，流式方案必须单独权衡Python迭代编码CPU与字节兼容，不作为紧急小补丁。

证据：
- /tmp/tushare-publish-hotspots-readonly-20260909.json SHA256 c53d360da353c4d4f65009f8f3cd006b1c3d7116d9f1bf9c1814a1a96f6ec91d
- /tmp/tushare-publish-sql-readonly-20260909.json SHA256 776d9bd62fbed59ce47c93670c5e29c8d45c8705183ae270d45eccd929d85416
- /tmp/tushare-publish-cgroup-quantmind-20260909.json SHA256 47077045f6a2c7c34a42fb66465762132256f7884c1979a3e473b8c61ada4727
- /tmp/tushare-publish-cgroup-worker-20260909.json SHA256 b2e8ea1d9da80e41c7ec53f0aa1f49ae58d7196927083b14a2a349f5e564a189
- /tmp/tushare-publish-coverage-equivalence-20260909.json SHA256 456d1b166180657c7d47aabaacb752555a2e9d58c5816f976f695f3118389553
