# Tushare 接入进度与恢复入口

目标：按 [总计划](tushare-integration-plan.md) 和 [任务书](tushare-integration-task.md)，接入账号支持获取的数据、完整保存历史/字段/原文/版本，云端持续采集、Mac 完整镜像。用户授权并行实施；单接口缺权限或文档/历史不完整时记录后继续其他接口。这个文件是当前状态索引，阶段证据追加到共享主树 `coordination/tushare-data/`，不能只靠聊天或内存续接。

## 已验证基线

- master e4a5212：七个 RRG 接口云端采集、Parquet/原始响应、不可变发布、Mac 15 分钟镜像和禁网读取；详见 [首轮验收](tushare-pipeline-acceptance-20260909.md)。全目录、全文和研究准入未完成。
- 云端 `/data/tushare/pipeline.sqlite` 保存正式请求/重试进度；`pipeline-status.json`、`CURRENT.json` 及 `releases/<id>/manifest.json` 是实际运行证据。Mac 当前目录 `~/Library/Application Support/QuantMind/tushare`。仓库中的数量只是核查时点，不替代实时状态。

## 当前工作与完整目标

| 工作项 | 状态 | 验收/下一步 |
|---|---|---|
| 全目录逐项台账 | 263 项目录已有快照；能力/权限尚未逐项实测 | 建立无遗漏覆盖台账，映射别名/类别/变更接口，未知不能算已覆盖 |
| 现有回填提速 | 已部署，首批360次/93.105秒，恢复自动消费 | SQLite v2 持久账号/接口频控，默认总上限 240/min、单接口 200/min；按实际批次吞吐重算 ETA |
| 已购九个文本 API | 九个合同已部署；首轮真实请求已完成，分来源历史回填中 | 主执行者集成、云端逐项实测后启用；保存默认隐藏字段与响应原文 |
| 结构化下一批 | 49 个合同已合入候选分支，覆盖主数据、A股/财务/宏观及基金/指数/可转债/期货 | 主数据发现、分区和满页细分、权限实测与本地查询 |
| 其余目录接口 | 未完成，全部保持台账计划项 | 按依赖逐批实现；无权限/停更/未知分别登记，不能静默缩小到上述首批 |
| PDF/附件、HTML正文与解析 | 云端已下载并解析15份；Mac真实PDF首页面核对通过，独立附件消费者接入中 | 安全下载、独立状态/重试，公告与研报各一份真实 PDF 页码核验，全部原文纳入镜像 |
| 通用查询与 API/Agent 消费 | 97接口和6财务别名已有合同及离线读/schema；API/Agent云端固定版真实读取通过，15类other待实测 | 目录/schema、日期/标的/字段/关键词/as_of 筛选、JSONL/Parquet 导出；Agent 引用真实已存原文 |
| 全历史回填、修订与缺口补齐 | RRG、文本、结构化、market四组持续回填；未证实上游全历史完整 | 分接口/来源/标的/日期/字段统计，满页细分、不可证实窗口保留 partial |
| 全范围镜像与版本增长 | 文档清单v2分片已部署，保留旧元数据对象；全部历史release索引闭包仍待补齐 | 纳入 schema/目录/所有历史对象，清单分块避免每轮复制完整大清单；固定输入与故障恢复 |
| 容量与运行监测 | 每轮保留 100 GiB 云端余量，尚缺长期增长预测 | 采集/文件/清单/备份按真实规模估算，需扩容提前报告，不能用容量缩小目标 |
| RRG/训练可用性 | blocked_data | 与可下载/可查询状态独立；历史分类、PIT、交易与持仓暴露验收前不启用 |

## 非阻塞缺口

- 目录中 36 项未抽取常规 API schema，需人工区分分类/特殊接口；权限不能从积分一概推定。
- 七类基线：在市 ETF 上市日缺失；CI005021 历史成员 N 空响应；行业历史名单/known_at 未证明。
- 官方未公开完整历史下界/分页上限的接口不能宣称取全；明确记录待查，不替换为未经支持的 offset 参数。
- 其他市场/分钟权限及已购文本的各来源权限待真实调用，不代用户购买新权限。

## 换端或压缩后的继续步骤

1. 读取共享主树 AGENTS、coordination/README、本主题最新增量记录、本文件与覆盖台账；先 `get_goal` 确认完整目标仍活跃。
2. 检查 Git worktree/分支/未提交文件与子任务进程状态，已完成提交直接集成；未确认进程终止不能重复启动作业。
3. 检查云端实际 worker 活跃任务、数据库状态和发布清单；仅进度文件存在不证明采集仍运行。已有生产锁/检查点必须复用。
4. 候选改动在独立 worktree 测试，无生产凭据和数据；主执行者统一合并、同步预检、云端样本、增量发布及 Mac 验证。
5. 将本阶段提交、实际证据、未完成接口/窗口和下一动作写入唯一增量记录，目标未完成时不标记完成。

## 2026-09-09 并行集成增量

- v2 提速配置已在双端源码/Git核对通过后，只重启专属 tushare-worker；账号240/min、基金持仓240/min，批次上限360次/100秒。其他市场同步继续运行。首批2026-09-08T17:13:26Z实际360请求/93.105秒，按120秒周期约180/min，是旧100/120秒的3.6倍；后续按新增分区与实际失败重算。
- 候选 v3：RRG/text/structured/market 分组轮转、跨重启公平游标、分组有界规划断点、按来源隔离无权限、日期满页拆分与明确分页、所有保留尝试原文及观察版本/目录schema进入不可变发布。58个新增接口的实现不等于权限/全历史验收。
- 仍需：新增合同真实响应审查、原文下载队列、增量中断补洞、分区完成闭环、清单分块、API/Agent和全目录剩余项。非阻塞问题保持台账，不因先跑通一批而完成总目标。

- 月窗口优化：启用 text_history_window=month，同1990年至今范围初始文本计划由295578降至13608（未计满页拆分），历史问答提问/回复双轴、9新闻来源和未知下界探测保留。默认day兼容旧行为；规划签名含window模式，变更只重置规划游标、不删除旧任务/数据。

## 2026-09-09 01:29 云端并行与 Mac 新数据验收

- 代码/配置双端核对已通过，专属worker启用 text/structured/market，RRG权重3、其余各1；月窗口模式、每family/phase每轮规划500项。第一完整并行批次360请求/97.459秒，进度检查点及数据发布成功。
- 真实首轮51个新增API已发出请求：32个接口有非空样本，另有当日/当前区间空响应，不能据凌晨空值确认没有历史。fund_manager分页已持续取得47000条并在Mac固定版禁网读取；news51、major_news20、anns_d978、daily5549、daily_basic5549、fund_nav5、cb_daily315、fut_daily64同样已读取，未用token或上游。
- 固定验收版 data-22f60c255291db1b01cec0f282f40569d3efb5eabe1ba486986902516553c8a0：10878个文件，Mac镜像校验通过。权威证据在 `/data/tushare/validation/extended-v3-probe.json`；不能把采样数量当全历史数量。
- 非阻塞：cb_price_chg真实返回40203无权限，已修复识别并隔离；fund_basic场外列表15000行、index_basic某市场8000行满页，当前基础发现仍partial。保留原始响应，未用未经文档支持的offset蒙混取全。
- 六个VIP财务批量接口合同已实现，但普通接口100行限制不能直接当作VIP批量上限，暂未加入自动回填，需有界实测其完整返回与分区方案；这是待接项，不是权限拒绝。申万分级成员等待L3基础发现后自动规划。
- 安全PDF/HTML队列、已有观察补登记及清单闭包已通过候选隔离集成测试，生产启用验收尚在进行。重复观察将复用同正文/URL的已存文件并保留原获取时间；同URL静默替换的周期检查仍是待办。
- 发现旧probe20个文件未进入最新清单，新机仅拉CURRENT会漏掉；正在以持久归档索引恢复旧release/孤立文件，恢复完成不能代替供应商全历史/PIT证明。


## 2026-09-09 02:10 附件与归档闭包验收

- 云端专属Tushare worker始终运行；18:09:17Z最近一轮332请求/90.076秒，done8212、empty2088、pending61678、blocked4、quality1、split_pending322。新增规划还在增长，不能以当前pending算最终全量ETA。
- 原文实测：公告PDF SHA256 `2c5ff20951ad646b135a695c710c6f7fc86ec2054743917a1d3438d40d45db15`，99616字节、2页，pypdf提取1976字节JSON。Mac已同步且以pdftoppm渲染第一页，标题/正文/页码对应；只有第一页做了视觉核对。证据 `/data/tushare/validation/document-archive-first.json`；全部附件完整性尚未完成。
- 旧归档恢复 frozen scan 已完成44877任务，纳入17641个文件，remaining0/open_gaps0。Mac固定版 `data-9bebfbeed1e70bcd12cc5436a3cd4f5277e8d7350fc757635cef96bfc701c6df` 共24164文件；原seed的20个原始响应/观察文件均在清单内且逐一SHA256通过，旧probe遗漏已修复。这不证明供应商全历史完整。
- 额外归档exec曾返回137；同窗口quantmind容器重启于17:50:47Z，Tushare专属worker未重启/OOM，随后归档自动续完。内核17:51:04记录的是另一Celery容器内存事件，不能当成Tushare归档OOM证据。
- 附件吞吐是独立瓶颈：18:09登记待下载88158、已解析15、retry15；此前74026队列按5份/120秒理想下限20.56天。正在改为独立Celery附件消费，复用durable锁/去重/重试；尚未部署，不能宣称提速已生效。公开附件下载不消耗Tushare API调用额度。
- 17个global接口合同/发现/规划已合入候选（原提交1d87b23、0b47613），HK/US代码保留source并归一化、未知起点和发现范围显式gap。35项agent隔离检查通过。尚未生产探测/启用，缺独立权限继续记录。
- 候选930bfd2降低发布峰值：jobs游标、scope SQL聚合、同一JSON编码bytes复用与及时释放；Mac流式hash，已校验既有对象只复查文件身份，变更对象重新hash，故障不切CURRENT；12项pipeline、8扩展pipeline、7global integration通过，82类/6别名store与global合同15项通过。没有清理历史对象，完整分块清单仍待完成。
- 候选9f3399e读取API的6项临时目录验收通过，但尚未注册engine/main与API代理，避免与正在进行的研究工作台发布争用。Agent消费与RRG PIT准入仍待后续。


## 2026-09-09 02:21 独立附件消费者已启用

- master/GitHub 5cba1cc，双端handoff passed：4323文件，摘要bb1aa2e8e708326270e7fa838015b3eb554c96b703a4e4ba3e027fcd3880465d。Mac仍使用原固定沙盒，无正式数据回灌。
- 新 quantmind-tushare-document-worker 已启动（1消费者、1536MiB、0.5CPU），任务 engine.tasks.tushare_documents 独立队列；现有采集任务每轮按配置派发，不重启共享beat。pipeline只登记文档，附件独立100份/90秒预算；频率/吞吐待实际计时，不把预算当达成值。
- 原Tushare批次d3b7a3a0自然完成后获取pipeline.lock写document_execution=worker，再只重启Tushare采集worker；首轮同时观察到API任务5b26f8c3与附件任务f2334d59。其他Celery/研究服务未重启。独立consumer已加入完整快照停写与恢复名单。
- 本地候选新增8项document worker测试、6项读取API测试、16项document回归均通过；此前42项pipeline/global/store组合通过（最初命令误写API测试模块名导致一项ImportError，改为test_tushare_data_api后6项通过）。无新增生产依赖。
- Mac无凭据客户端已更新新global模块与单遍流式hash；自动镜像仍工作。附件首轮实际下载/解析数量、长期吞吐、CPU/RSS以及最终镜像结果还需跟进。

- 18:24:34Z独立附件首批已完成：f2334d59，90.327秒/15项；累计25份parsed、1份parse_timeout、18retry、123499pending。不是100份预算全额达成；公开URL速度/重试仍需优化。18:24:48Z同周期API批次347请求成功发布data-1c3885a3063f0e4ff0e9300692af0a1e5321e7e871615a2101b60187c0777a66；下一附件任务9e4e72ca已收到，持续采集未停。


## 2026-09-09 02:45 Global及财务批量实测

- 23个显式只读接口14.710秒实测完成并保留原文/Parquet，证据 `/data/tushare/validation/global-vip-probe.json`，发布 data-67d158001bbd9a65efc0e0ea28d91fd866f13f7a437e16dc0a59ed8226d00dc7。
- 12个global接口可用并已启用自动规划：hk_basic/us_basic/hk_tradecal/us_tradecal/weekly/monthly/stk_weekly_monthly/stk_week_month_adj/index_weekly/index_monthly/index_dailybasic/hk_daily。HK日线2286行、HK基本2784行、股票周线5630行、两种每日更新周线各5552行。monthly5629超过文档4500保守阈值，index周/月线各1000满页、US基本6000满页，均不宣称取全。
- 五接口真实permission_denied：hk_daily_adj/hk_adjfactor/us_daily/us_daily_adj/us_adjfactor。保留完整目录并单列权限缺口，不代购，不根据10100积分推定独立权益。
- US基本分页四次2行交叉验证：缺省offset与0一致，offset1移动一行，offset2接续下一页；证据 validation/us-pagination-probe.json，证明本次0起点连续。其无过滤列表包含035420等数字代码，保留全部原始标的；US内部前缀仅供应商数据集命名空间，不能据此判定真实交易所/可交易资格。
- 六VIP财务接口都有样本：income9000、balancesheet7000、cashflow6400、fina_indicator10736、forecast1913、express66。官方财务文档明确VIP可按季度批量，但未给独立最大行数；候选只将上述已实测返回量作为更合理的饱和下界，row_cap_verified保持false，触界仍保守拆分。待部署后启用六类回填，不把样本较少当全历史证明。
- 53项pipeline/迁移/父子关系/global/structured/API/Agent隔离检查通过；新v4与Agent仍候选，未据隔离测试宣称云端业务已消费。新校验要求补实际Parquet SHA256后再部署。期权/黄金/外汇/国际宏观15类契约、文档清单分块正并行实现。


## 2026-09-09 03:15 v4及API/Agent生产验收

- ca2eca7双端handoff passed（4348文件，同HEAD/摘要）；只重启Tushare两专属worker和已确认无活动训练任务的quantmind，未重启其他Celery/研究worker。pipeline SQLite v3→v4迁移4.741秒，integrity_check=ok，迁移前一致性备份validation/pre-v4-pipeline.sqlite。
- 分区SHA256校验闭环首批解析120个父分区，其他575个split_pending仍保留缺口；不能把父子关系恢复等同全历史完整。旧周月线9802个pending可逆改为deferred_legacy_period_plan，原请求/尝试/数据保留，新标的范围计划接替。
- 文档v2真实首次构建：227338条引用、486个分片、7.792秒；顶层索引116237字节，随后的publish2.007秒。累计231份parsed、208532待下载（核查时点），附件吞吐仍是主要瓶颈；独立消费者继续工作，正在有界优化。
- 固定版data-3ad1585cfb1fae53f710a25b3588bc0f156cb6862f14e9dd5afcc3e995522f65：真实engine API查询HK00001/20260904 close69.85，耗时0.683秒；文档跨分片页返回3条/总227338；匿名和伪造用户头均401。本次采用既有服务身份，未冒充已验收用户JWT登录。
- QuantBot真实LLM工具调用2次（schema→query），7.838秒完成并输出69.85、release和历史不完整提示；数据工具upstream_calls=0。证据validation/api-agent-acceptance.json已保存。验收脚本最后打印含null delta时发生TypeError，只影响摘要打印；随后独立读取已存事件核对tool_result数据及回答通过，未重复模型调用。
- 112项pipeline/合同/分区/文档/API/Agent隔离检查通过；后续元数据闭包8项、HK特殊代码15项通过。没有宣称全仓测试通过。
- global恢复启用后发现hk_basic的5个额外供应商代码带!AE（02121、02228、03636、03668、03699），原!规则仍不够；family隔离生效，其他组继续。新的保持原后缀身份兼容修复待部署，记录在validation/global-planning-incident.json，不过滤这些标的。六VIP已启用；15个other接口合同/规划已集成，仍待实际探测后启用。
- 后续：修复global特殊标识并确认真实规划恢复；稳定周/月历史分区与近期刷新节奏；附件有界并发；other15权限/字段实测；全部历史release引用闭包、剩余目录、上游历史边界/PIT、容量增长和长期吞吐仍未完成。RRG仍blocked_data，总目标保持进行中。


## 2026-09-09 03:40 并行提速与其他市场实测

- 15个other API真实探测5.166秒：14个非空，LIBOR指定2023年窗口为空（不推断停更或没有历史），期权基础12000、期权日线15000均触及保守饱和阈值。全部原文/字段保留并启用history回填，证据validation/other-probe.json；表内permission_blocked与saturation blocked不同，不能把期权满页说成无权限。coverage ledger已补15项实测；完整目录仍263项。
- HK名单额外5个!AE代码已保持身份兼容，validation/global-other-recovered.json显示global/other规划成功、global恢复validation_passed。官方响应另证hk_daily仅1次/小时：此前导致整批60秒等待和两条任务达到重试终止。这次识别明确接口限额后只冻结该API，保留不明确限频的账号退避；学习间隔跨重启保留，配置hk_daily至少3605秒，两条quota等待任务已恢复pending，原尝试不删。证据validation/parallel-speed-deployment.json及原文对象08ecf0fd1fac65fdfea6c6ae6086cd7ef456bfd19938335cad4e16eab3bd024e。港股全历史速度受真实权益限制，未代购权限。
- 四类周月线改为固定十年桶及小尾窗：9643指数1990→20260909历史计划由年度/小周候选1080016降为96430；含近期115716。范围逐日连续，单指数周线桶低于1000行警戒；不删除旧请求。未完成历史规划跨周保留cursor，完成后才更新anchor，避免大队列反复从头开始。计划数改善不是实际全量ETA。
- 文档消费者启用download_workers=2：最多两路仅下载，随后一路解析；原文先落盘，持久claim/过期恢复、独立子进程总deadline、锁及版本保留。每轮100为阶段预算，一份PDF通常需要下载+解析两个阶段；20秒传输上限慢源会重试。单份解析资源预算未增加，实际提速待连续批次计时。
- 传输压缩实际验收：15733337字节固定清单，传输4429014字节、48.845秒（与已有镜像共享网络），SHA256一致。Mac镜像已更新rsync压缩；旧手动传输安全中止后复用已存文件续传，固定版data-bad7ca3db1f1a31565355a5116195f47046109f245f918c55527f05c324786c1共52692文件校验通过，补4754文件。该版5类other各2行及v2文档跨分片页已禁用socket/DNS实读，无Tushare凭据。FX:、SGE:是供应商数据集命名空间，不证明每行属于外汇/现货或具备交易资格。
- 159项Tushare专项隔离检查通过，涵盖全部test_tushare*.py；修正旧40203断言、模块导入路径及测试调度顺序后全通过，无新增生产依赖。c864a24双端源码/Git核对后启用配置；仅重启Tushare两消费者和无活动训练容器窗口的quantmind。主机其他服务未重启。
- 下批5个纯合同已提交（moneyflow_mkt_dc、moneyflow_dc、moneyflow_ths、etf_share_size、mkt_idx_bmk），59字段和纯规划6项测试通过；尚未注册pipeline/store/镜像及真实探测，不能把这5个算作已采集。目前注册97个数据集及6财务查询别名。12项下一批官方核查、pro_bar SDK别名与CSV-only Tick特殊页分类见coordination/tushare-data/20260908T192000Z-mac-next-coverage-review-c107c921.md。
- 继续项：验证限频隔离后API吞吐与双下载真实批次、接上5个补充合同、期权精确上市日补发现/未公开上限、全部历史release引用闭包、263项未实现与权限差异、全历史及修订PIT验证、容量/镜像增长监测。全目标仍进行中，RRG仍blocked_data。

- 03:44追加运行证据：新采集首批b97f4f8e为177请求/105.209秒采集段、117.498秒整批，成功发布data-72a638823926ffd7a05aedae082ebefe41e9ec92f965f66cd2dd13220d83a174；pending因新的饱和细分增至344613，数量仍在增长，不按此推最终ETA。三个相关容器running/healthy、OOM=false。双下载首批90.296秒完成10阶段（8下载尝试+2解析尝试），不能说10份PDF成功；后续已实测两份cninfo原文downloaded→parse_pending→parsed（5页/8页）。仍有下载超时和HTTP200非PDF内容，保留各自失败状态。当前汇总存validation/parallel-runtime-acceptance.json。159专项检查、双端源码/Git核对和GitHub master推送通过。

- 再一批实时汇总：19:44:36Z采集248次/91.262秒，done13988、pending344393；19:44:16Z附件32阶段/90.241秒（28下载尝试、4解析），累计parsed311，仍有215555待下载。云端余量309.43GiB。证据同上，不能把阶段数等同成功文件数。
