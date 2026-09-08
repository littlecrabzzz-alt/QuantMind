# Tushare 接入进度与恢复入口

目标：按 [总计划](tushare-integration-plan.md) 和 [任务书](tushare-integration-task.md)，接入账号支持获取的数据、完整保存历史/字段/原文/版本，云端持续采集、Mac 完整镜像。用户授权并行实施；单接口缺权限或文档/历史不完整时记录后继续其他接口。这个文件是当前状态索引，阶段证据追加到共享主树 `coordination/tushare-data/`，不能只靠聊天或内存续接。

## 已验证基线

- master e4a5212：七个 RRG 接口云端采集、Parquet/原始响应、不可变发布、Mac 15 分钟镜像和禁网读取；详见 [首轮验收](tushare-pipeline-acceptance-20260909.md)。全目录、全文和研究准入未完成。
- 云端 `/data/tushare/pipeline.sqlite` 保存正式请求/重试进度；`pipeline-status.json`、`CURRENT.json` 及 `releases/<id>/manifest.json` 是实际运行证据。Mac 当前目录 `~/Library/Application Support/QuantMind/tushare`。仓库中的数量只是核查时点，不替代实时状态。

## 当前工作与完整目标

| 工作项 | 状态 | 验收/下一步 |
|---|---|---|
| 全目录逐项台账 | 263 项基线及原 36 特殊页面已分类复核；额外 11 个正文链接另入发现台账 | 263 不是范围上限；分类页不等于子接口取全，目录外接口与失效文档继续核验 |
| 现有回填提速 | 已部署，首批360次/93.105秒，恢复自动消费 | SQLite v2 持久账号/接口频控，默认总上限 240/min、单接口 200/min；按实际批次吞吐重算 ETA |
| 已购九个文本 API | 九个合同已部署；首轮真实请求已完成，分来源历史回填中 | 主执行者集成、云端逐项实测后启用；保存默认隐藏字段与响应原文 |
| 结构化下一批 | 49 个合同已合入候选分支，覆盖主数据、A股/财务/宏观及基金/指数/可转债/期货 | 主数据发现、分区和满页细分、权限实测与本地查询 |
| 其余目录接口 | 未完成，全部保持台账计划项 | 按依赖逐批实现；无权限/停更/未知分别登记，不能静默缩小到上述首批 |
| PDF/附件、HTML正文与解析 | 云端已下载并解析15份；Mac真实PDF首页面核对通过，独立附件消费者接入中 | 安全下载、独立状态/重试，公告与研报各一份真实 PDF 页码核验，全部原文纳入镜像 |
| 通用查询与 API/Agent 消费 | 122 数据集及 6 财务别名已注册；本批 13 接口 Mac 固定版离线读取通过，已有 API/Agent 基础链路通过 | 新接口的逐项 HTTP/Agent 消费、全历史及单位口径仍分别验收 |
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


## 2026-09-09 04:10 补充接口与历史版本候选验收

- 5补充接口（东方财富市场/个股资金流、同花顺资金流、ETF份额规模、业绩基准指数）及7事件接口（分红、股东人数/增减持、回购、解禁、前十大股东/流通股东）已在独立worktree集成；注册109数据集及6财务别名。新增126输出字段显式保留，6事件无稳定事件ID，使用完整源行身份保留不同事件，不把观察时间冒充PIT。尚未据候选测试宣称生产权限或历史取全。
- 失败附件完整的有界响应保存为不可变.bin证据，保留HTTP/类型/解析失败状态；不会当有效PDF。历史CURRENT继承前任清单与映射，新Mac仅复制最新files也能禁网读取多代；覆盖中断、归档数据库丢失、无变化不造新版本、真实恢复变化仍发布。188项Tushare专项测试及ruff通过。
- RRG首个signal数据切片已经可独立结构验收：固定data-6e00837911a40223d75d7e4e7b770b4b60b4b7c9f2d208091c6e343f7283bee6；SSE交易日历推导2021-05-17预热起点，到2026-08-31共1286日，30行业38580行，按冻结协议排除综合/综合金融后28行业36008行，缺日/异常开收盘0。父独立禁网复验通过；证据/tmp/quantmind-rrg-slice-parent-20260909/report.json，可用scripts/verify_tushare_rrg_slice.py指定共享config重跑。分类历史版本/指数口径、成员PIT、ETF执行仍未验，不修改其他研究任务状态。
- 接续：云端只读接口样本、启用新family、历史归档catchup、失败原文真实保存及Mac新版本验证；全部263目录与完整历史仍未完成，目标保持active。


## 2026-09-09 04:30 新12接口生产与离线验收

- e8ee822经双端handoff passed（4378文件）后有界探测12接口，采集段3.567秒，11非空、stk_holdertrade指定股票/窗口空。全部126源字段完整返回，原文与Parquet逐行字段、数值、空值、请求日期/代码和源行身份审计通过；没有自动缩放单位。moneyflow_dc6000、share_float6000均明确has_more=true；前者6000不同股票，后者4股票且603448.SH占5959行，未来解禁2027至2029合法保留。完整单位语义表仍待补。
- 已启用supplement和equity_event自动回填，Mac无凭据镜像data-a3ab845ec2313d5224969ea70c9ac58b0f4677359dc1fd327a7053ac572a9913共65467文件校验通过，11非空API逐一禁网读取且全部源字段保留，/tmp/tushare-supplement-events-mac-verified.json。云端证据validation/supplement-events-probe.json。第二次Mac固定data-87e70f6d838889c27b955e7d55e4070e7970a7666317c39bafa613b454464a11共68107文件，29份失败.bin原文逐一hash通过，缺少原release路径的历史ci_daily仅用archives回退读取成功；/tmp/tushare-archive-bin-mac-verified.json。
- 真实运行发现stock_basic并集5909含T600018.SH，阻断事件family严格6位校验；其他family继续。候选修复保留T供应商身份，规范为SHT600018、不合并SH600018，旧Parquet只在读取投影兼容、不覆盖文件。另按父响应代码与已有发现取并集扇出，重入保留旧child/证据，不把基础名单误当完整全集；未验证全集仍false。明确has_more=true低于本地阈值也将判饱和，不用count=0推空。213项Tushare专项回归通过，正做第二轮有界生产恢复。
- 下一批7期货（85字段）及6财务/研究额外接口纯合同/惰性规划已提交，仍未注册运行或生产探测。fina_mainbz须将请求P/D/I类型加入源身份；期货持仓不能把fut_basic.ts_code当symbol，weekly_detail周序号语义尚未验证。详细交接见本主题202417Z/202554Z记录。
- 非阻塞继续项：旧结果中未处理has_more的回溯审计、原有扇出父节点补见过的代码、跨数据集统一标的发现仍需增量补全、API非200失败响应原文保留、完整字段单位语义、历史修订/PIT、所有263目录剩余接入、归档release-only catchup（正在恢复，open_gaps核查时0并非完成）。RRG signal结构切片通过不解除整体case/breadth/ETF限制。

- 04:35恢复验收：5b4ec20经双端handoff passed（4390文件）后，maintenance复用pipeline锁修复两个真实饱和父分区：moneyflow_dc发现外补115代码，共6024子任务；share_float5909子任务，父记录的4股票完整保留。两个父分区仍split_pending/universe_complete=false。事件recent/history各规划500项、planning:equity_event已validation_passed，证据validation/observed-fanout-recovery.json。只重启quantmind与专属acquire worker，专属documents未在本轮重启；全部三个容器running/healthy/OOM=false，两专属队列已恢复且各有真实活动任务。
- Mac最终固定data-dcb1c3839a99d210ec466603811ce46d104daf60a941aaa7616aa5f810c029ce共70482文件校验通过（本轮再补2375）；T600018.SH/SHT600018与600018.SH/SH600018禁网分别读取，保留不同源身份，证据/tmp/tushare-historical-stock-identity-verified.json。运行汇总validation/supplement-events-runtime.json；余量核查305.97GiB，无须本轮扩盘。新批次处理中的快照不能用前一批状态时间冒充新吞吐。

## 2026-09-09 05:20 补充13接口生产与离线验收

- b0e1845 双端 handoff passed，随后仅重启 Tushare 采集 worker 接入阶段耗时和 DCE 标识修复；此前228db0d已部署13接口。当前注册122数据集及6财务别名。250项Tushare回归通过，后续目录一致性5项定向检查通过。信用7运行候选2a4bbb1尚未部署，不能计入122之外的生产覆盖。
- 15次首轮请求5.906秒，11接口非空；追加两个不带原过滤条件的发现请求1.172秒，fut_holding与fut_weekly_detail各4000行。全部13已取得非空样本，共9868行原始记录。两个4000与stk_surv400均保留饱和缺口；stk_surv已建立5909个证券子任务，发现集合仍未证明完整。
- 原文、观察SHA256与Parquet逐字段相等，P/D/I分别35/10/4行，所有144文档字段包含空响应的schema均已返回。Mac固定版 `data-e3d0b8e8d539fb775b226e3e8799b131591e1b3c34965384ae7b287ef3adfcd5` 共81278文件完成镜像；断网且禁止密钥读取，全部13逐字段对账和固定版查询通过、upstream_calls=0。云端证据 `validation/extra13-probe.json`、`extra13-empty-discovery.json`、`extra13-acceptance.json`；Mac证据 `/tmp/tushare-extra13-mac-verified.json`。
- 实际fut_basic有11204个代码，其中6个L_F/L_FL/PP_F/PP_FL/V_F/V_FL带下划线。过严校验曾只阻塞futures_extra组，已修复且实际planning:futures_extra于21:16:10Z恢复validation_passed。未删发现代码或修改正式配置绕过验证。
- 新实际口径缺口：周统计返回20191、201904等混合宽度的供应商周编号；无条件4000行仅覆盖本次返回的2019—2020部分，不能据2026查询为空断言停更或全历史完整。期货周线trade_date=20260904却返回end_date=20260831/20260907/20260908，两个日期轴按原值保留，计算截止口径与历史可知性仍未验证。持仓排名需要exchange/symbol成对补齐，不能只用股票式单参数fanout。
- Mac自动镜像曾因plist指向已清理的uv临时Python而以78退出；改为固定`tushare-client/.venv/bin/python -I`，已有健康环境离线复用，新环境准备失败不替换旧任务。实际LaunchAgent安装后退出0且完成新固定版镜像；保持每900秒运行。详见[tushare-mirror-installation.md](tushare-mirror-installation.md)。
- 阶段计时第一真实批263请求/90.028秒，总110.677秒：initialize2.551、planning4.336、archive5.093、acquire90.184、document_registration0.020、publish8.491秒，failed_stage=null。不能把90秒当整批墙钟；保持240/min账号门、接口独立门及160/180秒任务边界。下一性能候选针对已测重复SQL扫描与排序，尚未据模拟索引收益宣称生产提速。
- 原36个无常规API页面已全部复核：33分类/说明、2个SDK pro_bar页面、1个CSV交付页。直接子目录均在基线，但正文另发现11个链接文档，其中rt_k/rt_etf_k为独立权限接口，6个链接当前正文缺失。新增discovered_entries保留，不改原263基线count。188/422仍作为需正文复核的种子；因子库独立权益、SDK与CSV交付、账户写/删均不能凭积分或目录存在自动纳入HTTP回填。
- RRG固定价格/日历切片结构通过，下一可并行步骤是固定输入消费适配与因果性技术验收；历史行业定义、成员known_at、ETF映射/可交易性仍独立blocked。全量数据回填不作为这一步隐含依赖，但未运行策略发现、完整回测或更改研究case。


## 2026-09-09 05:50 队列提速、信用7及RRG并行推进

- 40bea6a 已合入并推送 master；双端 handoff passed（4450文件，源码摘要0c3c9f7ae87971e9a3119dddd634887a0497323774c0f1cc57afc25a9cbd2221）。276项Tushare专项隔离测试通过，含40万pending查询计划与期货重复分片回归。当前注册129数据集及6财务查询别名；注册数不等同全历史取全。
- 两专属消费者自然排空后，SQLite正式一致性备份551518208字节，SHA256 d42289d8f372a27b02dfc0ab95fafb4e5eb07d54280732201864756629cbe03f；v4→v5迁移0.867秒、integrity_check=ok，458584 jobs / 30301 attempts / 250 capability / 119 request_gates数量一致，仅增加3个队列索引。证据validation/pre-v5-backup.json、v5-deployment.json。旧v4-only程序不能直接打开v5，回退须保留v5兼容，不能盲目恢复旧备份丢失新增进度。
- 7信用接口真实请求2.075秒，6非空共9242原始行：margin3、margin_detail4441、margin_secs4468、block_trade164、pledge_detail165、pledge_stat1；slb_len指定20260904为空，保留未知状态。58字段含空schema均返回，非空原文/观察hash/Parquet逐字段及日期轴校验通过。block_trade有29条完全重复源行、pledge_detail有1条，原文与Parquet保留；查询视图去重数量不能冒充真实事件数。证据validation/credit7-probe.json、credit7-acceptance.json。
- 信用7配置已启用但planning:credit_extra实际validation_blocked：funds发现22205标识，包含0000371.OF、1610142.OF以及1500011.SZ、5010021.SH等7位历史基金代码，6位校验拒绝。保留原始发现与family-local gap；structured已独立修复候选，不截断或丢弃代码。其他组继续，不能报告信用历史回填已恢复。
- 两个真实期货满页父分区已追加137个exchange/symbol持仓子任务及66个保留原始week值/类型的周度子任务；旧证据不删，coverage_proven=false，全集和饱和末端仍有缺口。证据validation/futures-observed-recovery.json。
- 仅重启quantmind和Tushare两专属worker；US原定时任务保持同一id继续，未重启普通/research worker。实际acquire60926005、documents039a38db均恢复；21:48:57Z首个v5批次331请求/90.048秒采集、109.752秒整批，failed_stage=null。升级前最后一批270请求/90.221秒、108.361秒整批；单批约多23%请求，不保证持续比例或据此推全量ETA。Mac持久镜像运行环境已刷新信用模块，固定版镜像正在执行，尚未宣称本批离线验收完成。
- 用户再次要求减少串行等待：云端采集/附件与Mac固定数据消费并行；remaining已用已有原算法跑通RRG28行业坐标候选，父独立复验待完成。PCF471/472纯合同95c3ba1（6离线测试）已交付但尚未runtime集成；实时rt_k/rt_etf_k纯合同已入master但未启用，仍依赖独立权限与过期快照门槛。历史分类、成员known_at、ETF执行仍blocked，不跑策略发现/完整回测。
- 05:48核查云端可用300.41GiB，本轮无需扩容；45万级任务还会随发现/分片增长。后续：信用7位源标识恢复、Mac本批禁网复验、RRG坐标父验收、PCF接入、目录剩余与长期吞吐。总目标持续active，不等全库下载才开发消费端。

- 05:53完成追加：Mac固定data-e12e0274cf2c5acd3b36c99f0a7ab52abd43e86c5fab435b200c367129a7d597共88800文件校验通过，本次补2758文件。其保留的credit验收版data-90d7f3967529f2253f546d1b26c3a135ebdf6c8a81a15ff07484877e5dc1f75a禁网逐字段核对9242原始行通过；block_trade视图135、pledge_detail164与原文重复数对应，slb_len空观察保留、查询明确不可用且无上游回退。证据/tmp/tushare-credit7-mac-verified.json。
- RRG父独立断网复验通过：28行业×968日=27104坐标，220/60/20预热、3截点截断/未来扰动、逐行业缩放、同走势中心100、缺值拒绝通过；CSV SHA256 66d4ca27445090b528f346499aff1a8d661771c57b7676dc84b1d5d0be83b0e6与子验收一致。报告/tmp/quantmind-rrg-coordinate-parent-review-20260909/report.json；48个月末有47个下一交易日映射，末端边界仍gap，整体blocked_data不变。消费验收脚本及PCF纯合同已合入675301b，PCF尚未注册运行。信用7位修复4e414e4（22项隔离测试）已交付独立候选，下一轮部署恢复。


## 2026-09-09 06:15 信用恢复与ETF篮子生产验收

- 44d1748 已合入/push master并经双端handoff passed（4470文件，摘要e7b21fb1f7a7dd6ecf443998ebf113d6197640b4befb04518b8a1cee7b99e862）。本批290项Tushare专项隔离回归通过；131个数据集、6财务查询别名（store总键137），不等于完整历史覆盖。仅采集consumer自然排空；只重启quantmind和tushare-worker，document及普通/research worker未重启，当前采集/附件均已恢复。
- 信用7位源基金身份兼容已实测恢复planning:credit_extra=validation_passed，funds22205、专属etfs1829、credit_securities8877。7位代码保持独立，.OF原文保留但不进入信用请求；统一内部前缀及交易信用资格仍有明确gap。recent信用31项、history500项初始规划成功，未删旧任务/原始发现。22:13Z自动作业（排除capability探测）信用done24/empty41/pending7843/split_pending1，证明自动回填已推进，仍非全历史完成。
- PCF两接口及转融资宽范围发现合计3请求1.125秒：etf_sh_cons(517030.SH/20260615)300行，etf_sz_cons(159051.SZ/20260625)100行，slb_len无日期2811行。slb本次覆盖20140102—20250725，不能由上界断言停更或历史全集；原20260904空观察仍保留。27个文档字段全返回，原文/观察hash/Parquet逐字段、原始scalar类型及请求日期/代码匹配通过。证据validation/etf-basket-probe.json、etf-basket-acceptance.json。
- SH样本72条qty=0且含HK/SH/SZ；SZ14条qty=0且含BJ/SH/SZ与1条申赎现金，均未筛除。PCF数字/字符串/空值混列不能直接存Arrow：原数量字段为nullable text，每行_raw_numeric_json保存原JSON类型；schema.source_scalar_encodings说明如何还原，Arrow/JSONL/API不会自动还原。全部原始响应与raw row identity不变。篮子数量不是持仓权重，精确known_at及完整PCF表头/申赎单位仍未知。
- 两PCF已启用recent/history各500起始规划；22:13Z自动done49/empty17/pending1934。云端API固定版查询SH300/SZ100行，约1.008/1.234秒，原文/Parquet/API全部值和scalar类型对账通过，upstream_calls=0、匿名401；本次为既有内部服务身份，非用户JWT登录验收。证据validation/etf-basket-api-acceptance.json。
- Mac持久runtime已更新新模块，LaunchAgent此前自动一轮exit0；随后固定data-cdf881db31f95b1aefcbdc92de75fdc6e65d8e47b9baec75d6b459ef6f25a680共96064文件校验通过（已有自动镜像基础上补12文件）。断网且禁凭据的两个PCF+slb共3211行原文/Parquet/查询审计通过，字段编码说明可读；证据/tmp/tushare-etf-basket-mac-verified.json。没有改动其他研究配置或回灌Mac旧主库。
- 当前生产批22:12:08Z316请求/89.953秒采集、112.814秒整批，failed_stage=null；云端余量298.54GiB。只读全scope评估时Tushare目录约20.123GiB分配量、41.7万待采集任务与31.6万待下载附件；队列还会扩展，不能当最终分母或线性ETA。细分JSON /tmp/quantmind-fullscope-assessment-20260909.json及本主题220033Z记录。
- 找到两项影响持续进度的实际机制：全局signature让不相关family的历史游标反复回退（9500→3000→1500等真实manifest证据，任务未丢但重复规划消耗预算）；documents状态256桶在新增1000随机记录时约98%桶变脏，manifest归档也有重复字节。规划修复17e2332已有62测试和原版3/3复现失败，独立候选未部署；元数据分块/安全硬链接候选由text隔离开发，未动生产/既有文件。
- 新5项互联互通/板块资金流纯合同已合入bb1fc15，5项离线测试通过，尚未runtime或探测。47/49/196/197当前官方正文缺失继续保留历史获取义务，正查已存官方抓取/官方Git历史以准备有界探测，不推定停更/无权限。全263基线+11发现文档义务、全部历史/修订/PDF仍未完成，goal持续active；RRG价格坐标技术验收不解除整体PIT/ETF准入限制。


## 2026-09-09 06:35 有限规划进度与不可变清单去重

- eb3bf64已合入并推送master，双端handoff passed（4487文件，源码摘要083ab607482cf1fd6cb3d3515d021b628161b56de6745725aea85074fa70eb41）。315项Tushare测试、Ruff与diff检查通过；含124 API及11家族共135组实际生成器依赖投影一致性验证。
- 规划签名改为每家族的选中合同/配置与有限发现快照，未完成的历史/近期扫描保持固定anchor；新增发现等待本轮完成再进入，真正配置变更仍重建该家族计划。近期跨日按最多6天重叠窗口追赶。旧签名首次迁移安全重扫一次，作业身份与已采集结果保留；没有声称已消除islice前缀扫描成本。
- 云端两次真实规划后，11个history游标500→1000且第二次reset_reason均为null；481106作业与36529尝试数量不变，两轮各识别5500已存在作业、0新作业（迁移仍在重扫旧前缀），约3.22/3.06秒。备份validation/pre-finite-planning-state.json，验收validation/finite-planning-alias-acceptance.json。schema仍5，无数据库迁移。
- 固定发布data-40ef395ff3b9e7358cc98e55a88380ad1237d2469dbf31d2134e36e44d6ffe8b，前版data-7c4df2b4375be23a4e1b505233876b4bc69d5c9c6f228b5eeccd8d8308d30ae1的51612576字节清单已验证archive/release同inode、相同SHA。新清单采用经路径/字节校验的安全hardlink，同盘不额外复制；原有重复文件未清理，不能说回收了历史空间。Mac mirror保留远端manifest原始字节，避免重排JSON破坏摘要，持久client已刷新。
- 专属消费者自然排空后仅重启tushare-worker，文档消费者恢复；新真实采集任务1f80c34c与文档任务234c1a72均活跃，两个队列恢复。research为空；通用US同步未被本轮停止。后续实际正常批次与Mac固定镜像验收另补。
- 并行继续Connect5 runtime、schema3两层文档状态索引、龙虎榜/游资4接口合同。schema3合成写入减少约74%-87%仍非生产收益且初建inode更多；四个旧互联互通正文缺失保留缺口，不阻塞已知接口。完整历史、原文附件与RRG PIT准入义务仍未完成。
- 正常运行追加证据：22:36:45Z 326请求/122.069秒，22:38:45Z 334请求/119.488秒，均failed_stage=null、无规划reset。发布仍占约18秒，不能据此声称吞吐全面提升；新作业0说明有限迁移扫描仍经过既有前缀，并非没有后续历史义务。
- Mac两轮均verified：第一版40ef395f共106578文件、补5335；第二版data-e45c6159e515a82a9ae020d12c05bb619f7789e8c2c22206a0c8495922267f96共107697文件、补1118。第二轮将本机已有40ef395f清单复用为archives，54300820字节、同inode/SHA验证通过；全清单逐文件校验后才切CURRENT。证据/tmp/tushare-planning-alias-mac-verified.json。


## 2026-09-09 06:56 Connect5生产接入与旧接口证据

- 93b6343已合入master/GitHub/云端；完整319 tests、Ruff及双端handoff passed（4499文件）。实际11方向/类型请求8.412秒、6292原始行、58输出字段，原文/观察SHA/Parquet/固定读库及请求日期/type全部一致。5接口已enable_connect，近期77新作业，历史初始423新作业；动态签名确认原11家族历史未重置。现136采集API及6财务查询别名，不代表全量历史完成。
- fixed data-2e5f447c9fc136fc016c864d19c21a953ae872c1969a255a116b71e6ebe77012：云端API15次分批全列6292行与存储一致、upstream_calls=0、匿名401。Mac补4066文件、共111764全部校验；禁网禁凭据逐字段原文和查询验收通过。报告validation/connect-acceptance.json、connect-api-acceptance.json、/tmp/tushare-connect-mac-verified.json。
- 22:51:17Z正常批331请求/125.204秒、failed_stage=null，发布19.344秒；Connect自动非probe done19/empty12（当次快照），history已推进1500，完整任务仍扩展。云端可用295.69GiB，本轮无需扩盘。仅重启quantmind+tushare-worker，文档队列恢复且新任务3cef7903、采集523080b8实测；通用US/研究未中断。
- 4个旧接口有界raw探测：moneyflow_hsgt 1行；ggt_daily 1000行、has_more=true；ggt_top10空参数校验失败50101；ggt_monthly名称拒绝40101。后两者不视为无权限，月度历史义务不删。仅保留归档清单不足以镜像新raw；已定向验证并归档8引用文件、发布b93d6be5，证据validation/connect-legacy-closure.json，Mac闭包复核另记。
- 覆盖台账5条改ingested_partial/available_observed；47补当前能力证据，196/197作为额外发现条目补入，原263基线保持、discovered由11至13。目录测试改为允许有非空原始探测证据支持的权限更新，不能把初次unverified固定成永远未知。
- 并行候选：schema3 9cf3a60 + descriptor校验0ea2e88，独立Python3.10审查证明损坏descriptor不再推进CURRENT；旧缓存leaf等完整性风险仍记录。龙虎榜/游资纯4d2f953+runtime b5b6a80，含hm_list错误字段定点修正、hm_detail.tag显式请求，未部署；hm_name二级拆分仍gap。
- 旧接口引用闭包Mac复核完成：固定data-b93d6be5405e42c5ae4c2cee7b27876f65e2eea09af25920b398761c2c55a65c共114928文件、补2029，四个原始response及四个observation全部在发布清单内并通过SHA。/tmp/tushare-connect-legacy-mac-verified.json；不增加未审API归一化注册数。修复闭包时只自然排空采集消费者，随后已恢复，无再次重启服务。

## 2026-09-09 07:22 并行集成与等待发布记录

- 用户要求减少串行等待：历史采集与文档作业继续；独立工作树并行推进接口合同、字段审计及吞吐评估。父候选 `d6cc1fe` 已集成文档schema3两层索引、龙虎榜/游资4接口、历史列表/IPO/BSE映射/市场统计4接口及显式请求字段覆盖检查；364项Tushare隔离回归11.152秒通过，Ruff和diff检查通过。仍未进入共享master或生产，不计入136个生产采集接口。
- 字段保护补充Shibor/LPR的1w、1y、5y等数字开头列；非空响应漏回显式请求列保存原数据并标schema_gap。基金经理分页及指数分区重试两处测试原mock漏列，补齐请求字段后原闭合断言通过，没有弱化保护。13个已核对非空实样本未发现请求列遗漏，不能据此证明供应商所有隐藏字段已取全。
- 23:18:44Z生产批328请求/90.416秒采集/117.602秒整批，publish13.744秒、planning6.468秒；pending463704、done26414、empty14784。队列仍扩展，此数不作全历史分母或固定ETA。云盘df约264GiB可用，包含在建全量备份占用，不将磁盘变化全归因Tushare。
- 07:00全量快照PID422770先完成在线预复制/扫描，07:19:53因`Celery work active`以75/TEMPFAIL退出；未发布新快照，现有服务仍running。期间父未暂停任何消费者，也未执行schema3迁移或新接口probe。备份失败独立记录，不阻止离线开发，不自动重试或停止其他活动任务。
- 本机已准备但未执行 `/tmp/tushare-schema3-migrate.py`、`/tmp/tushare-trading-event-probe.py`、`/tmp/tushare-listing-extra-probe.py`及旧互联互通过滤探测。下一步发布前重查活动任务/双端一致性，自然排空两专属消费者；新API读取器先兼容旧/新索引，正式DB备份、meta1→3迁移、全核心表与全部便携行SHA比对，再做账号样本、固定API和Mac禁网验收，恢复并核验两队列。不能直接回退旧DB覆盖新增进度。
- 全263基线+13额外发现义务不缩减；RRG固定坐标技术验收已通过，但历史成分可知性/ETF等仍blocked_data。无需等待所有PDF下载才继续RRG数据消费验证。

## 2026-09-09 07:41 schema3与八接口生产闭环

- f2cd52e已合入master/GitHub及云端，handoff passed（4535文件、88249b3e80c50872bb9ad0ecf89a5179594506a9582b61f610ca8dc810455d30）。正式144采集合同及6财务查询别名（KEYS150；扩展CONTRACTS137+基础7），不可将某个子注册表长度冒充全注册数。完整364隔离测试及Ruff通过，本次台账/目录修正另15定向测试通过。
- 两专属队列自然排空后，先升级quantmind读取器，四子服务health200，再备份documents.sqlite并迁移document_index_meta1→3。420331520字节备份、352512文档/412528引用/3465尝试全内容摘要前后一致；全部便携行与DB比对一致。首次构建9.928秒、noop0.578秒，4096叶/16描述块。旧新API各9页通过，匿名401；完整证据见文档存储页。
- 八次真实请求分别2.789/1.717秒，8API全部非空、6928原始行和91输出列通过raw/观察SHA、Parquet及过滤语义对账。hm_detail.tag246行皆null但列存在；IPO按ipo_date；BSE原码不合并生效区间；daily_info新增SH_FUND_REITs标签保留。8接口已启用，近期39新任务、历史初始961新任务，原12历史组签名/游标没有回退。
- 固定data-1a593ee58c333ebb02b025b1529f342c914a82cf389ac7878eeb34c73f45d668：19次真实API全字段6928行一致、upstream_calls=0、匿名401。Mac新增4141文件、总130814全校验；8接口禁网/禁凭据原文、Parquet、查询全部一致。另固定schema3迁移版350k文档等全部便携行在Mac与云端DB摘要一致，旧schema2可读。
- 仅重启quantmind和两Tushare worker，恢复后采集7b68c095-ba31-48d5-80b8-88d31446b6ac、附件f85881ce-c050-44b2-9009-d6910b2d2dd1实测活动；普通US任务88fe98db-f897-42a9-932c-cc1a84860e10保持。23:36:37Z正常325请求/115.710秒、publish12.562秒，failed_stage=null；不能由单批或noop索引耗时推断持续提速。空间262.29GiB可用。
- 自动非probe已推进trading done13/empty24、listing done14/empty21。IPO无筛选2000行实际饱和blocked，日期分区仍继续；research_report已捕获真实file_name缺列且原1000行保留，文档矛盾待复核。全部8条台账改ingested_partial/available_observed，基线263+发现13不变。
- 并行下一候选：limit_extra纯cd1da8a+runtime91fc460，43 tests通过；附件脚本挑战分类5246705，43文档测试通过。两989B原文实际是JS挑战页，未执行或绕过，cninfo超时归因仍未知。候选未部署，下一轮审查集成。全部历史、修订、附件、PIT/RRG准入仍未完成，goal持续active。
