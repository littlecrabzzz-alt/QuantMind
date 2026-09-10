# stock_context 与文档登记生产验收

- Root 在 `master` 合入 `30894be` 和 `47f239f`，形成 `f71d8ab`、`15e6722`；六份候选交接记录形成 `8193d14c40f30e65f42f1800c04ac1f1a19d2903`。`origin/master`已推送；Mac→云端handoff通过，5900源码文件，digest `a8acee66d0751ab6d3be8ab85253e770da3ad495bf31a3e47d69e41dd801e74e`。合并后Python3.10完整Tushare测试851项通过、skipped5，日志`/tmp/tushare-merged-full310.log`；两候选各自Ruff/diff check通过。
- 仅取消两个Tushare队列接新任务，等待active自然排空；随后只重建`tushare-worker`、`tushare-document-worker`。容器内签名确认新代码，二者healthy/running、OOM false、restart0；其他市场、研究、主服务未重启。
- 规划任务`1844c1fa-de3f-4875-ba85-117c861fba35` SUCCESS，0请求、137.554秒。`planning:stock_context`恢复validation_passed；非法来源1条作为`planning:stock_context:stk_rewards:malformed_stock_supplier_identifiers` coverage_unverified保留，合法股票6295。该批执行时的54个已观察合法code/end_date组合全部计划，history新增54。后续采集产生新薪酬对象，收据时已观察组合218、计划仍54，明确`all_actual_pairs_planned=false`；等待下一900秒规划周期，不重置游标或假装全集完成。
- 采集任务`2df4252c-594f-4c64-813c-4623ae16ee0a` SUCCESS：360请求、acquire83.306秒、整任务105.411秒；最后接口按500rpm、最小间隔0.12秒决策。文档登记首批500行0.918秒，attempt123391偏移402。下一任务`1b5697a0-65e5-4a2b-bf6a-8a3004b7cbc2` SUCCESS，从同一断点再提交500行至偏移902，1.081秒。文档任务`5ba2680a-d069-46f4-a3a3-caecfb2a7dd0` SUCCESS，79件、91.589秒；部署后观察未再见documents锁错误。
- 部署后12分钟`tushare-worker`日志统计HTTP200=448、HTTP429=0、供应商频率错误=0、soft timeout=0。配置仍`tiered_v1`、500rpm、batch360/90、planning/publish900；`stock_context_apis`含`stk_rewards`。发布任务`fc0c089c-e482-4f80-9605-fdb099dcc3c5`成功151.884秒，CURRENT切换`data-0c8bff9f9d09b952da909fad391bf2604e2dcf60ab78afeca8804d5c065b4671`，但160秒尾延迟未解决。
- 发布checkpoint候选`bbc818a`留在`codex/tushare-publication-checkpoint`，未合master/未启用：它证明三阶段崩溃恢复及字节等价，但本地总耗时更长、最长阶段未缩短，无法证明生产160秒上界。继续以现有原子CURRENT和失败重试运行，不提高超时或删减历史清单。
- 不可覆盖收据`/data/tushare/validation/stock-context-document-budget-20260910T014826Z/acceptance.json`，5163 bytes，SHA256 `854f21a97f43eac4933e53d644a1d921d7fdbe73886b9b15ecc38c05263c01b4`；回读SHA、源码head和4个任务状态通过。标准Mac镜像在一次rsync30后手工重试成功，先到`data-ac275…`，随后LaunchAgent第76轮退出0并追平云端`data-0c8bff9f9d09b952da909fad391bf2604e2dcf60ab78afeca8804d5c065b4671`，验证517286文件；旧指针在失败时未动。云端74G、磁盘剩余160G，100GiB停采保护有效。
- 完整历史、218新观察组合的下一轮计划、publish尾延迟、105万以上附件待处理、RRG成员PIT/ETF/研究准入均继续未完成；本记录不关闭总目标。

## 后续生产闭包（02:44Z）

- `1a01997`、`4e4b58d`、`9a6685c`、`a22f107`依次合入；最终`master`/origin/cloud为`a22f1079c6f75b1a2f1d494a2e8078dc3382db2e`，5917文件digest `b33c9bf96e8ed6a8210242fffc221ff81fc239a05811e85c8415db00002ecd71`。合并后877项Tushare Python3.10测试通过、skipped5，Ruff/diff通过。只重建采集worker，500rpm、900秒周期、160秒soft limit均保持。
- 观察组合增长到524。原冻结快照需至少29轮/约7小时15分后才刷新，因此新增有界append scope并前置执行；真实规划先将54推进到500，最终暂停采集后的固定快照补齐再新增24，78.885秒、0上游请求，断点offset524/done1。只读复核actual524/planned524、全集包含为真。收据`reward-period-fast-append.json` SHA `d9acfb2a44acccae931609a496e33964630b3cbbef95d7e6a5384bac287eb798`。
- 流式清单编码在约102MB基准上保持最终SHA一致，中文最长路径下降12.0%、峰值RSS736.9→443.8MB；真实首发仍160秒超时但已切换CURRENT到`data-e201969a…`，幂等重试140.155秒成功到`data-c59d2208…`。新增精确release intent覆盖今后CURRENT swap后/checkpoint前崩溃窗口，不依赖mtime、不追认旧无证据版本。
- 文档短窗约105.6万pending、166 parsed/20min（约498/h），冻结算术88—97天但队列增长；1次finish写锁失败后恢复。保持2下载/1解析和100GiB保护，不在缺少分阶段计时与百万临时队列证明时增加消费者。
- Mac固定版已验证`data-d1524977…`、522363文件；较新云固定版等待标准镜像。完整历史、后续增量、发布总时长、附件、RRG PIT/ETF仍为开放项。

## 最终验收补记（03:14Z）

- 生产发现追加范围刷新时前500个existing任务错误消耗新增预算；`8faad2dc`修复为仅按新插入任务计500条预算，合入后最终`master`/origin/cloud为`3a69fe159fea94ca967fa7a933fad77a9b8c21d5`，5919文件，digest `7b3022af9bba2870e11878ab92b3745a60e3e7befd5849b15b4000f413084ae9`。完整881项Tushare测试通过、skipped5，Ruff/diff通过。
- 固定624快照一轮扫描existing524并新增100；刷新后的737快照再扫描existing624并新增113。独立只读复核actual737/planned737、全集包含为真，断点offset737/done1。两收据SHA分别`2fcd3f0a35b0feba6050cb01cffa764db330aaf0cbc82e3c345c8c62e072fa63`、`ac1afd8c86612d557062cb1855ed715adeb2117b2f7c7b1c9d39d38edff14bc3`，独立报告SHA `22dfb7c3335c7f999b5dcb867b13a1b2bec5a100b4c6911ff39a66934d484847`；三次规划均0上游请求。
- 最终自动发布`2cdb1b56-fbe6-4015-b2ed-e730aaf1bc1e` SUCCESS、144.088秒，CURRENT为`data-2c8715f9920400555ccab3f739c982938cb127f72db1a1c6c0bb18378b6f1662`，待恢复intent0。最终运行收据SHA `b83de442ce035cf1e34b1c6f7945d4ab0db24d2fa42f2adc2f5b80c47de1d25d`；权限脱敏补充收据SHA `3157a8e44a48104cb6765e79a0324bb9bfcfe2fb8768616aa7b3bce11ad2b641`，确认10100→2026-12-05后8100的提醒语义，不含Token/订单凭据。
- 最终只读文档状态pending1059185、parsed14750、blocked2609、retry5；两worker healthy，可用磁盘168352239616字节，100GiB保留线不变。附件吞吐与RRG PIT/ETF继续作为开放项，本记录不关闭总目标。
- Mac标准LaunchAgent第82轮exit0，CURRENT与云端同为`data-2c8715f9920400555ccab3f739c982938cb127f72db1a1c6c0bb18378b6f1662`，本地manifest文件数529362、镜像目录约65G；未启动重叠镜像进程，未向Tushare重复抓取存量，也未回写云端。
