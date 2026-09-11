# Tushare 接入进度与恢复入口

目标：按 [总计划](tushare-integration-plan.md) 和 [任务书](tushare-integration-task.md)，接入账号支持获取的数据、完整保存历史/字段/原文/版本，云端持续采集、Mac 完整镜像。用户授权并行实施；单接口缺权限或文档/历史不完整时记录后继续其他接口。这个文件是当前状态索引，阶段证据追加到共享主树 `coordination/tushare-data/`，不能只靠聊天或内存续接。

## 已验证基线

- master e4a5212：七个 RRG 接口云端采集、Parquet/原始响应、不可变发布、Mac 15 分钟镜像和禁网读取；详见 [首轮验收](tushare-pipeline-acceptance-20260909.md)。全目录、全文和研究准入未完成。
- 云端 `/data/tushare/pipeline.sqlite` 保存正式请求/重试进度；`pipeline-status.json`、`CURRENT.json` 及 `releases/<id>/manifest.json` 是实际运行证据。Mac 当前目录 `~/Library/Application Support/QuantMind/tushare`。仓库中的数量只是核查时点，不替代实时状态。

## 当前工作与完整目标

| 工作项 | 状态 | 验收/下一步 |
|---|---|---|
| 全目录逐项台账 | 263 项基线及原 36 特殊页面已分类复核；额外 13 个正文链接另入发现台账 | 263 不是范围上限；分类页不等于子接口取全，目录外接口与失效文档继续核验 |
| 现有回填提速 | 已部署，首批360次/93.105秒，恢复自动消费 | SQLite v2 持久账号/接口频控，默认总上限 240/min、单接口 200/min；按实际批次吞吐重算 ETA |
| 已购九个文本 API | 九个合同已部署；首轮真实请求已完成，分来源历史回填中 | 主执行者集成、云端逐项实测后启用；保存默认隐藏字段与响应原文 |
| 结构化下一批 | 49 个合同已合入候选分支，覆盖主数据、A股/财务/宏观及基金/指数/可转债/期货 | 主数据发现、分区和满页细分、权限实测与本地查询 |
| 其余目录接口 | 未完成，全部保持台账计划项 | 按依赖逐批实现；无权限/停更/未知分别登记，不能静默缩小到上述首批 |
| PDF/附件、HTML正文与解析 | 云端已下载并解析15份；Mac真实PDF首页面核对通过，独立附件消费者接入中 | 安全下载、独立状态/重试，公告与研报各一份真实 PDF 页码核验，全部原文纳入镜像 |
| 通用查询与 API/Agent 消费 | 212 个采集接口及 6 财务别名已注册；已完成批次有固定版云/Mac读取证据，实际启用与缺口见下方增量及台账 | 新接口的逐项 HTTP/Agent 消费、全历史及单位口径仍分别验收 |
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


## 2026-09-09 08:14 并行推进、limit4与月窗上线

- 用户要求减少等待：历史采集持续，新接口在独立worktree准备；固定版API/Mac验收与采集并行。本轮暂停窗口约16分钟，后续先完成开发/离线测试，再短时排空/部署。RRG已有较高调度权重，按所需数据范围逐项验收，无需等全部附件和其他市场历史。
- runtime bbe2f9e已合入master/GitHub/cloud；handoff passed，4562文件、8cb42112c2ac6e4bf789c8fe2ef871e89d0417434343fbd50da19fc885b79f3f。148采集API及6财务查询别名；limit4的20请求/1233来源行、55显式字段与10种类别对账，固定版云端API及Mac禁网查询全部通过，去重975行；详见涨跌停接入文档。其他13未完成历史游标保留，近期70+历史430初始任务不代表历史总量。
- 月窗减少未饱和历史区间初始请求，满额继续二分，不承诺固定倍数提速。391项隔离回归11.946秒、Ruff/diff通过；计时另Python3.10独立62测试/AST等价复核。source_challenge已产生真实尝试3786/3795（988/984字节），原始bin SHA通过、parse not_attempted，不执行挑战；validation/source-challenge-runtime.json。
- 重启quantmind和两专属worker后，采集4c3447b8-ea3f-49d2-9ca8-c154a5e3a094、附件ba365ffd-bdc6-4b78-b098-9378578a65e1及两队列实测恢复；US88fe98db-f897-42a9-932c-cc1a84860e10保持。00:11:51Z正常批329请求/118.014秒、failed_stage=null；发布14.069秒，其中coverage/closure4.065、attempts/stat2.432、retain_previous2.178秒。单批定位不等于持续收益，账户本地预算240次/分，不能靠多worker线性加速。云盘可用260.67GiB。
- research_report精确trade_date=20260121、正常11列请求仍回85行/10列，file_name缺失，不是仅范围请求或1000行满额所致。原文/schema_gap保留，known_field_gaps增加证据；不删字段、不推断永久无权限。此前10个近期/历史固定样本只读比较见本主题记录。
- 下一concept4已并行准备：e1041f2→03d8d74→55848e1，40相关测试；未合入生产、未probe、未启用。先独立整合测试再安排发布，保留THS成员历史/PIT/未知cap。旧互联互通精确过滤探测仍未执行；263基线+13发现、全历史/修订/附件及RRG准入仍未完成。


## 2026-09-09 08:36 concept4生产闭环与下一批并行

- 上一turn为实质进展，本轮继续全目标：e1041f2→03d8d74→55848e1已集成为100e4df并发布master/GitHub/cloud，404隔离tests+Ruff通过。152采集API+6财务查询别名，未缩减263基线+13发现范围。期间采集仅在备齐候选/脚本后自然排空，恢复后再做固定版验收。
- THS目录/日线/最新成员、DC三类别已启用。8请求6.139秒、5803行、40已知输出字段全部返回；目录A/HK/US及七类type保留，隐藏市值非空，成员三个历史/权重字段均null。目录A/typeBB样本实际全.HK成员，目录count306/成员309不一致，全部保留、不按目录exchange/count过滤，历史PIT限制仍在。
- 固定e1386fc1全5803行原文/Parquet/独立查询及30HTTP对账通过（匿名401、上游0）；Mac新增4058/共159836文件校验、24样本证据SHA及禁网禁凭据查询通过。详情与完整release ID/报告路径见docs/tushare-concept-extra-intake.md。
- 两专属队列恢复，真实采集1f84450c-2506-4d74-90bb-b9768b49878d、文档768c6e8e-d036-415a-9a75-a164eaa33ddd活跃，US88fe98db保持。00:33:56Z正常批265请求/120.401秒、failed_stage=null，较少请求不直接等同退化（成员响应更大且共享负载变化）。自动DC done18/empty3、THS daily done4/empty3、index done1、member done11/blocked4/pending1956；四阻塞为返回5099—5549行超过本地未知cap保护值，原始全行保留且不推断真实截断。history目前仍在跳过成员近期项，未称历史完成。空间259.74GiB可用。
- 并行耗时复核：部署前两正常批335请求、118.729/119.694秒，发布约15.1秒；coverage/closure约4.48、attempt+stat2.43—2.68、retain_previous2.22秒。固定120秒节拍下，单缩短publish不能承诺提高请求数，暂不为这点增加迁移。物理元数据占用审计另由structured整理，未删数据或改schema。
- 下一dc_member/dc_daily纯候选523d32b已push codex/tushare-dc-extra（17字段、7tests），runtime94d66a1已在独立worktree完成并push codex/tushare-dc-runtime，417项测试通过，未上线/未probe/未enable。补每日历史成分与OHLCV，官方历史下界/PIT/分类映射/单板块饱和仍待验。旧互联互通过滤探测、全目录剩余接口、全部历史/修订/PDF/RRG准入继续推进。

- 空间专项只读核算：/data/tushare所选文件按device+inode去重后28.16GiB，其中元数据17.68GiB（62.8%）；release/archive10.45GiB、历史文档索引7.03GiB、原始响应6.35GiB、Parquet1.99GiB、附件0.86GiB。此数不含目录、未列子目录、数据库及外部备份，不是整盘总量。164对旧release/archive同大小不同inode，潜在去重3.628GiB，尚未逐对SHA验证或实际回收；当前新别名已安全硬链接。最新不同版本manifest约66.7MB，若大小不变且每120秒产生新版，静态估算44.72GiB/日；不是实测日增长。证据/tmp/tushare-storage-review-20260909.json及003856Z主题记录。
- 优先并行准备常规tick发布间隔候选（默认0兼容，后续可设900秒最小间隔）：API采集、原文、observations/attempts、文档尝试继续每批持久化，手动publish立即，减少重复全量清单；保留审查确认后续固定版仍包含全部原文/观察/尝试，减少的是中间状态索引快照。尚未实现上线或修改生产频率，实际新鲜度还受120秒tick和Mac15分钟轮询影响，不能承诺严格15分钟。旧副本去重另留方案，不删除历史、不改manifest schema。


## 2026-09-09 09:17 DC2闭环与RRG优先级核验

- 上轮e87dc2b集成是进展；本轮已发布DC历史成员/板块日线并启用，154采集API+6查询别名。7真实请求6.447秒、9069原始行、17字段；去重16重叠成员后9053行，经12云端HTTP和Mac禁网读取全列一致。Mac新增9439/共180862文件校验，固定0a801f56完整ID/报告见docs/tushare-dc-extra-intake.md。wide成员has_more=true明确缺口，不将8000行称完整。12个未完旧history游标保持。
- interval900于01:07:09Z启用。首次自动发布01:09:52Z，333请求/130.596秒，发布24.962秒；随后两次真实deferred为01:11:37Z与01:13:23Z，整批104.882/105.522秒，CURRENT校验1.014/0.982秒，采集继续且固定release保持e9da1c41。最早01:24:52Z才到期，最终新manifest闭包尚待真实验证；不可将此记录视为完整节奏验收。证据由structured保存在/tmp/tushare-live-interval-acceptance/，水位从manifest实际覆盖的API55186/doc4432算起，未误把抓取时新增181/12条当已发布。
- 并行RRG薄适配da146cf→f7aa20c仅3新增文件，父重跑3专项tests及3产物SHA通过。固定输入36008价格行、1934日历行，48月末映射含20260831→20260901；复用既有坐标报告，不重算策略。input-report SHA490dad76ec985055155534cdcb7662de4b07684850de4666a3c356669331ab8f，位置/tmp/quantmind-rrg-case-inputs-20260909-final/。industry_members/etf_prices/etf_holdings/etf_pcf仍未准备，gates unknown/blocked_data，未改他人研究文件。
- RRG关键股票三API已启用且20260908真实sample_ok，停在各1分区的原因是structured同优先级namechange前缀、后续8712个index_daily及API顺序历史枚举；daily_basic历史尚未排到，不能误诊为权限或下载完。准备对原队列的21近日期+最多90研究切片作有界优先级调整，不重置tries/result/历史游标，不变更其他数据组份额；尚未执行时不宣称已提速。
- 风险5纯1e701c6与runtime1e6716a已在独立分支通过439tests，下一批准备中，未上线/未probe/未enable。父尚未pick；实际probe与云/Mac固定版验收脚本已备好，见/tmp/tushare-risk-probe-handoff.md。全263基线+13发现、剩余接口/历史/修订/PDF与RRG准入继续推进。


## 2026-09-09 09:28 发布降频真实验收完成

900秒配置保留；自动e9da1c41→6a46d2c0实际947秒，5次deferred期间采集继续。6438个新增文件（261619850字节）SHA及新manifest闭包通过，173文档尝试逐条对比通过，缺失0；未手动publish/调时间。常规批发布开销约1秒，到期仍约26.69秒；不能以此承诺整体吞吐倍增。完整水位/版本/限制与证据见docs/tushare-publication-interval.md。本周期Mac追平还需单独验证，DC固定0a801f56离线闭环已通过。


## 2026-09-09 09:36 RRG小切片优先与周期Mac闭包

- 原采集批间自然取得pipeline.lock，操作rrg-window-20260909-de9677e3c154482bb4432954c6cbd998已commit：81个已有pending任务仅priority提至24，30个缺失daily_basic研究任务经原Pipeline.enqueue入同history epoch，总111目标=21近窗+90研究切片。研究日期为20210517及20260803—20260831；不等同整个20210517—20260831完整历史。全planning_state与config不变，未重置tries/result/state或改group权重，无上游请求/手动发布。首次有界锁重试返回busy_no_changes，后续1秒间隔有界重试在第27次成功；没有因此暂停/取消采集队列。
- 原111次重复过滤候选已改成一次按组索引的目标扫描和主键回读。helper SHA c20ec97aaa5bd84c6eae619e1b745a53b7bc526bb3997812df42dcfcff090b73，prepared证据SHA f0142841114db94b77249a6e9c018a0bd52e94f73d08b517daab32aec04a638c，云端validation/rrg-priority-adjustments/下分别保存prepared和committed收据；prepared单独存在不视为提交成功。
- 标准Mac mirror已追平6a46d2c0（新增6448/共188149文件校验）；父独立重算本周期6438文件SHA、261619850字节全部一致。完整版本与证据见docs/tushare-publication-interval.md。后台新采集尚未到下一发布时仍只在云端持久化，不能把6a固定版当实时全部数据。
- 风险5父候选8c2e938已push，442隔离tests13.218秒/Ruff通过，尚未生产。remaining继续技术指标/筹码/bak_daily纯5以合并后续发布批次；text只读评估structured组内长期饥饿与最小修复方案，不写生产。全量目录、完整历史/修订/PDF与RRG语义门槛仍未完成。


09:37后置只读核查通过：全部111目标的job/logical_key/epoch/请求/group/priority与提交后证据一致；配置SHA仍一致，已完成/空结果未被重置。16个目标已有新尝试：daily done5/empty2、adj_factor done5/empty2、daily_basic done2，其余目标继续pending。该计数来自云端当前队列，新增响应尚不能算已进入Mac当前6a固定版。证据validation/rrg-priority-adjustments/rrg-window-20260909-de9677e3c154482bb4432954c6cbd998.verified.json及Mac/tmp/tushare-rrg-priority-postcheck.json。


## 2026-09-09 09:58 RRG优先窗口落盘与联合候选

- 111个RRG目标已全部产生新尝试：81非空、445887源行；30空响应均由同固定版SSE交易日历证实休市。303个原文/观测/Parquet文件SHA、35个已知请求字段、全部源列/原始代码/行身份逐行通过。原始daily ah_vol/ah_amount存在null并完整保留，不填零。证据`/tmp/tushare-rrg-priority-readonly-report.json`，SHA4050a55f101c85e4ecb06be6aa317c70ec766a43baa9a53e84eb3b374d5332d2。
- 固定自动版data-ea8b819290385b2d630d940e2e3bd041f0c51ae59fe62c1256ba7ea4c9ff5af3包含49个新尝试，其余62在该版之后采集。包含旧probe/修订的全部对应API分区独立去重后，与实际reader的49个API/日期全列比较194099行，差异0；HTTP/上游0。此处未验证后续版或Mac，不把有限窗口当完整2021—2026/RRG PIT验收。
- 父候选6e28dae整合风险5、技术5及structured独立API轮转/3近期:1历史机会；468项Tushare隔离回归24.736秒、Ruff及diff通过。曾用模块路径运行技术专项因scripts测试导入路径失败；改用仓库原discover入口后14项通过，不是代码故障。风险29字段、技术342字段均显式请求并保留来源语义；真实权限/过滤/字段仍待probe，不计入已生产154接口。
- schema6仅增pending表达式索引，不改历史生成器、旧游标和任务内容；40万模拟任务索引约10.7MiB/239ms、全任务SHA不变。生产需停两专属消费者并自然排空、先一致备份再迁移；旧代码拒绝6，禁止用旧DB覆盖升级后新增进度。候选未发布，采集继续。
- 五个/tmp迁移/风险技术probe/云Mac共用verifier已准备并检查Python3.10语法；启用helper继续独立准备。统一发布前先把测试和脚本做完，恢复采集后再做固定API/Mac验收。额外并行启动HK/US八财务接口纯契约研究，独立权限未知按缺口记录，全263基线+13发现的范围不缩减。


## 2026-09-09 10:36 并行接入、风险技术上线与Mac闭包

- a68c6d9已发布风险5、技术5、schema6公平轮转和到期单独发布；随后其他任务完成Qlib发布，主树已到510dd57，未打断两Tushare worker。联合隔离470 tests/Ruff通过；schema5一致备份1056563200字节，迁移2.01秒、8表行数/内容SHA与rowid不变、integrity_check通过。备份和部署证据见云端validation/pre-v6-prepared.json与Mac/tmp/tushare-v6-deployment.json。两专属消费者仅在02:10—02:23Z部署验证窗口自然排空/恢复，未撤销普通US任务。
- 风险9请求223来源行，stock_st/st/stk_shock去重221行、18已知字段通过非空样本；stk_high_shock和stk_alert共4次仅空返回，不能据此判无权限或字段已验证，注册但不启用。技术8请求17338来源行、去重17202行，5接口342字段全部返回；单日/范围或代码过滤的3组非空全列比较通过。已启用风险3+技术5，台账10项同步真实状态；全263基线+13发现范围保留。
- 固定data-cc8ed219d8021aefadf998ab5bb6604c7498981d89ede6122c0578f24040db55完成云端原文/Parquet/reader与认证HTTP验证，再经标准Mac mirror校验209734文件；风险与技术Mac禁网/禁凭据读取结果相同。技术HTTP大表明确仅单股scope，不称全17202行经HTTP；完整行对账在实际store路径完成。报告/tmp/risk5-mac-verified.json、/tmp/technical5-mac-verified.json及对应cloud报告。
- 同一固定版已包含RRG111全部303文件，本地SHA全通过；此前未发布62目标的实际reader全列对账251788行、缺/多/列差0，16休市空查询。完整报告/tmp/tushare-rrg-mac-cc8-closure-report.json及023118Z主题记录。有限研究切片已可离线消费，不代表完整2021—2026或成员/ETF/PIT通过。
- 不等全历史结束：remaining并行补stock_context7运行候选；foreign_financial8与publish优化已准备待审；text只读分析历史前缀/规划耗时，structured验收自动发布恢复。生产仍共用账户限流，部署集中批次，接口开发/固定版验收与采集并行。技术history首批500全部跳过近期前缀，实际新增历史0；不能把配置启用称作历史已拉取。
- 02:33:31Z实际自动acquire_only批217请求、121.664秒，planning25.018秒、acquire90.237秒、无failed_stage；CURRENT已推进2e1585a2…，checkpoint1788920958。手工发布14.6秒发生在quantmind容器，不能作为0.75CPU专属worker性能证明。前序publish_only具体结果另核验。剩余历史/修订/文本附件/独立权限/PIT缺口继续记录，不缩减范围。


10:39补充：真实自动publish_only任务e7b0e64f完成SUCCESS、零请求、performed=true，整轮49.245秒、发布47.438秒，CURRENT推进2e1585a2…；后续两正常采集186/217请求均成功，发布与采集分轮的恢复链已验证。详见tushare-publish-first.md与/tmp/tushare-publish-first-chain-evidence.json。性能agent查明技术近期前缀86737项；500/轮预算会到第174轮才进入history，现offset4000未重置。已并行准备“预算只扣history、绝对源offset保持且有扫描时限”的最小候选，未部署、不承诺吞吐倍增。


## 2026-09-09 10:47 下一批候选准备

父独立分支0056b55已合并foreign_financial8、stock_context7和单次coverage聚合/提前释放旧manifest优化；498项联合Tushare测试22.608秒通过，Ruff/diff通过。实际注册计数179采集API、185读取数据集（含6查询别名），这是候选计数，生产仍164采集API。两组运行接线冲突已保留全部family/标识/日期轴与179扩展fixture，没有取消任何断言。foreign8完整192字段、stock7完整68字段（含managers.resume非默认列），默认均关闭。

两个agent分别准备有界真实probe及固定云/Mac验收，root复用逐接口启用helper，全部已知字段不豁免；第三agent修复历史预算跳过近期前缀，维持绝对源offset/signature，并增加scan/time界。候选全部备齐前不暂停生产。02:43:37Z生产正常269请求、126.717秒，pending991107，云盘可用253.46GiB；队列增长与完整历史待办保留，不把pending计数当已下载数据量。


10:53联合候选f2d8ec3已加入历史预算修复，最终507项回归23.321秒/Ruff通过；Python3.10规划相关63项通过。当前准备进入单次部署窗口，schema保持6，无游标重置迁移。foreign8/stock7有界probe和固定版verifier、逐API启用helper已准备并经隔离夹具验证；实际权限/字段与云Mac闭包仍待本批执行。


## 2026-09-09 11:15 十五接口上线与两个等待瓶颈

- 8b4553c生产发布通过handoff：4677文件，source_digest f0d9cf7e2d6719f20331ff1b7d04279b279112727816f587b22c019d93686ad3；两次Syncthing未追平时拒绝，实际逐文件一致后重试通过，没有覆盖冲突。两Tushare队列02:53:28Z取消消费并自然排空，03:00:22Z确认恢复；采集64f63c4a-b79c-42ac-859e-ec4d2cf24981、文档46292b6a-3b80-4893-86e5-d7aa1281852b，普通US88fe98db保持。schema仍6，注册179采集API+6读取别名，不代表全部可用或历史完成。
- foreign8八请求全部permission_denied，8原文+8观测文件进入固定版并SHA验证，全部禁用。stock7十请求：盘前/开收盘竞价拒绝；管理层/薪酬/九转/AH共1801来源行、去重1775、43字段非空样本完整，68字段中其余25未验证。仅管理层/九转/AH启用（固定347行、36字段）；薪酬1428行完整保存，超过本地未验证1000行保护阈值，自动启用暂缓，不把它说成已证明上游截断。
- 固定data-ed2f8b460437e0fdbd025565a2e2d20105c7a770d629c341a83e76de10aa3faf原文/Parquet/reader全列通过；管理层公告/任期、薪酬报告期、AH双代码与九转精确日期/freq保留。三组动态非空全列对照相同。stock云端8HTTP（含401、7筛选scope）通过，不声称全1775行全部经HTTP；foreign无非空数据，不伪造可用证明。耐久证据和helper副本保存在/data/tushare/validation/intake-batch-20260909T025328Z/共13文件。
- Mac本批标准mirror明确exit2 TimeoutExpired，前两自动轮也同错，旧CURRENT保留。只读取证86,253,968字节固定manifest压缩rsync11.941秒且SHA一致；旧日志无法确定具体超时stage。镜像修复e89b→8a098de已部署master/cloud，handoff4685文件通过，parent13专项通过、agent513全tests通过。只更新Mac运行client、不重启采集；有界压缩清单传输、已有manifest/alias校验复用和安全stage诊断保留全部对象/历史。本次正式mirror正在运行，结果待验。
- 历史规划修复保留旧technical signature逐字节不变，offset7500→87237→87737，5接口各200个history共1000真实入队，但全部pending/tries0/无attempt。进一步确认technical组仍按priority20近期优先，8384近期压住priority55历史；只有structured原先享有3近期:1历史。最小消费修复e0b→4115b14已通过联合520 tests23.167秒/Ruff，复用schema6索引、保留RRG/权重/gates/旧structured键，对其他已启用family独立API轮转。本轮只排空/重启采集worker，真实history请求仍待恢复后验证。
- 薪酬54个观察期每期1—60行，含非季末20070625；20251231单期22行与全期对应全列一致。后续按已观察期分片必须保留未知期间、code-only再发现及父覆盖缺口，不能把54期当全集或只枚举季度末。15项台账已更新真实权限/存储/启用状态，Mac闭包暂标pending。全目录、完整历史/修订/附件/PIT目标继续。


## 2026-09-09 11:29 Mac闭包与真实历史消费验收

- 标准Mac mirror修复后实际exit0，固定data-630dbb0ca721022e19d02337cc578d3cd5b4f61f797fa31f900ed192be36f278共218864文件通过校验，新增9129。随后对固定ed2f8b46的foreign8/stock7分别离线验收，云Mac的release、probe SHA、全部probe_samples、dataset_checks和gaps逐项相等。15项台账更新离线状态；11拒绝权限项仅证明拒绝响应已归档，并未变成可用数据。
- 公平消费4115b14随master044f373云端核对通过，4688文件/source_digest 8a21aef32b41ab313e5d1860991b53b3da9f171f821b3000830c55e7beaf1dd3。只采集队列03:13:21Z自然排空，03:19:13Z已恢复；文档和普通US任务保持。最终联合520项隔离测试/Ruff通过。
- 只读实测五技术API累计14次真实history HTTP200；cyq_perf22行、cyq_chips3586行，均000001.SZ的20180101—20180131；其余12次为空，保留empty_unverified。14份观测SHA一致，旧signature及100个原任务身份不变，history offset推进91237。此后新增历史响应是否发布并到Mac尚未验证，不混同前述固定版。证据tushare-family-fairness-after4-20260909.json SHA5afb30e9ff7ad365c13e753ded5a8fadd0cd8075fa8f0541886bd26549005683。
- 不等待历史全量结束：market_sentiment7与cross_asset_extra6独立纯合同并行；后者候选24dfca5已推送，6 API/296字段/4隐藏字段、6项Python3.10测试/Ruff通过，尚未运行接入。前者识别tdx_daily目录漏6数字起首字段，必须完整保留，后续定点修正目录。生产仍共用账户限流，不因开发并行叠加无控制采集。完整历史、修订、权限、附件、RRG成员/ETF/PIT继续未完成。

11:30补充：market_sentiment纯7也已完成并推送cc0de16，101完整字段、7项离线测试/Ruff通过；与cross_asset_extra6合计13 API/397字段，均仅候选，尚未运行接线或真实权限验证。后续从两分支独立review集成，不扩大生产已启用计数。


## 2026-09-09 11:52 下一13接口联合与目录/规划修复候选

- 父独立候选合入cross6运行96515d8→bf88123、market_sentiment7运行62c1956→ff8fb26，公共注册/规范化/标的发现/固定reader/镜像接点冲突保留两组。候选192采集API、198读取数据集；仍未生产或启用。完整397字段、4隐藏列，热榜全46变体及market/is_new/hot_type/tag/idx_type身份保持，跨资产namespace隔离并保留全部source列。
- 修复官方目录parse_document字母起首正则导致的42遗漏列：TDX6、五利率API36。六页重新读取的HTML SHA与旧目录完全相同，确认是本地提取遗漏；利率enqueue实际字段集合改前后相同，因原extra_fields已补足。目录现在完整，TDX已有gap改成已复核note；未来实际响应、历史不因目录成功而判完整。详见tushare-catalog-numeric-fields.md。
- 最近7真实采集批共1508请求/898.38秒，约100.72次/墙钟分钟，规划191.60秒占21.33%；300最近attempt无权限/限流但含空/饱和/schema等需独立处理。没有把30rpm当瓶颈或提高资源/额度。规划诊断+单次immutable原文去重d3b9c32→8a1c259已并入：保持request维度旁路，不跨tick缓存、不改schema/旧游标/任务。重复夹具40次records→1、结果同；真实收益待生产新timing验证。详见tushare-discovery-timing.md。
- 554联合Tushare隔离测试26.092秒通过；随后目录note/精确全列断言13专项0.703秒通过。旧21个family规划签名在基准配置逐项不变，新增2family。真实cross6探测及固定verifier已完成12项隔离验证；sentiment49call/120秒探测和固定验收仍准备中。全部helper齐备并审查后再进入集中部署窗口，生产采集继续。
- 标准Mac mirror已实际exit0，固定data-86aebb78840094da306bdb92aaa89876e199f55733c727a9e1068927869a63e4新增7949/共230624文件校验；正在对此前14历史观察及CYQ3608源行补做该固定版独立离线对账。新13接口不在该版，不混同候选与数据完成。


## 2026-09-09 12:18 十三接口真实探测与并行提速

- 30b3194已发布master/GitHub/cloud，4718文件/source_digest dc5e821c33d581941c82378c620b9a233facaa79ec5f4ed4e07d3b7b9faa2fbf核对通过；192采集API、198读取数据集。采集消费者03:55:12Z暂停接新任务、03:57:26Z自然排空，03:59:44Z恢复；文档和普通US消费者保持。注册不等于全历史可用。
- cross6完成12次真实请求，8009来源行、296已知字段全部返回；sentiment7完成49次真实请求，31250来源行、101已知字段全部返回。TDX成员和开盘啦成员bulk各3000行触及保护阈值，原文完整保存、保留饱和缺口，不据此启用或称全集。热榜market/data_type和其他过滤仍以独立验收为准。两次探测沿用共享额度和现有pipeline锁，没有再暂停消费者。
- 探测固定发布data-41d91a26636bde7c6c83020e36671e012aa845af1c2ea8e07f6772aae9f80435于04:16:56Z完成、17.89秒，无上游调用或启用。两份云端固定verifier和标准Mac mirror并行推进，台账登记真实探测、离线验收仍pending。
- 上一86aebb固定版的14历史观察/30目标文件独立Mac验收已通过：CYQ22+3586行全部源值/身份/as_of一致，456关联文件校验；12空响应仍不代表历史完整。报告/tmp/tushare-family-history-offline-verified.json，SHA7e0b49a2fd62c230792d67a3f3b45df68b15c59184209fc1ecf323a8a8157be8。
- 新计时首批9038aaee在document_registration阶段SoftTimeLimitExceeded失败：已持久化209响应，规划39.55秒、标的发现34.20秒；后批cf4df246成功220请求，发现28.19秒。原文去重真实命中0，不宣称已提速。最小字段投影b385c59→2295b84保留全部12发现列与严格行长/重复列语义；106项Python3.10相关测试和父558联合测试通过。宽表夹具输出同、临时峰值179→102MB，生产收益尚未验证。
- 不等全量历史：独立并行准备债券/可转债下一8接口；核查RRG单时点最小补数，20250903—30的20开市日×daily/adj_factor共40已有任务pending，无需新增。优先调整尚未执行；历史成员PIT与ETF数据仍单独缺口。完整263基线+13发现、历史/修订/附件范围保留。


## 2026-09-09 12:29 十一接口启用、本地闭包与RRG四十项优先

- 固定41d91a两份云端verifier完成：cross6零gap，sentiment7保留2饱和、2完整性提示及35市场输出映射未验。397已知字段、61原始请求全部来源/Parquet/reader全列、日期/代码过滤和9组非空对照通过。云端匿名401+7受限查询共8HTTP，大表仅明确code子集，不称所有行全部经HTTP。
- 标准Mac mirror已完成8758新增/247648文件校验；同固定41d91a禁网禁凭据独立读取与云报告6共同键逐项相等。数据去重后cross6共8003行、sentiment7共31247行。两份Mac报告SHA分别ebc9b7b608081a7a4771b9e94376448faf2eee528c680452897fe177f9385720和93ead6a13669230315f47d181d8797d1e0837c38804c911d33ea1780ae85a19b。
- 逐API评估后启用cross6全部及tdx_index/tdx_daily/kpl_list/ths_hot/dc_hot，共11个；tdx_member与kpl_concept_cons保持禁用，已有3000行各自完整存档，分片/全集未验继续待办。新增两family规划1000history+350recent任务，旧配置与无关规划记录保持；无上游请求。启用发布eac7f042完整ID见台账，配置审计/data/tushare/validation/cross-sentiment-enable-20260909T042558Z-274e6062.json。热榜市场语义未知仍保留，不借启用宣称PIT。
- 99fb562源码/Git双端已核对，4727文件，source_digest86fcb7892291a4064a4bd7ed9a2cf686f6a43ddb96693c69f94311c0363b8042。采集04:19:54Z暂停接新任务、04:20:54Z自然排空，只重启tushare-worker，04:23:54Z恢复；文档/US消费者保持，4服务健康检查通过。新真实d7ac29bf批SUCCESS，184请求/137.67秒，规划28.01/发现23.23秒。较前成功批发现少17.6%，但整批131.18→137.67秒，尚无整体吞吐提升证据。
- RRG40优先事务真实commit（04:25:48Z）：operation rrg-diffusion40-20260909-b0b0f1b914894a928565212be8f0fd28，40已有pending任务priority45→24，0新增，config/planning/scheduler提交时保持。后置只读40身份/优先级一致，04:27:42Z仍pending/无attempt，不把排队当已下载。prepared SHA71bcb2332d83eff05b8841d74274d7766ac47913e2f43f8c52d19d230f759a7c；收据在validation/rrg-priority-adjustments。完整日历骨架、历史成分PIT和ETF缺口仍待办。
- 下一bond8纯合同91d5e7d已在独立分支推送：70完整字段/22默认隐藏列，7隔离测试通过，runtime继续并行准备，尚未生产或探测。各原文报告/两个verifier/镜像/部署/提权helper证据已归档validation/intake-batch-20260909T035512Z。完整263基线+13发现范围不缩减，继续历史/修订/权限/附件接入。


## 2026-09-09 12:41 Bond8联合候选与成员合法分片

- 上轮为实质进展；本轮父0661c3b上合pure91d5e7d→b4faca3、runtime70af978→b2bfb14，新增8债券接口70全字段/22默认N，200采集API/206读取dataset候选。镜像安装copylist补齐；572全套隔离tests26.687秒/Ruff/diff通过。生产仍192，新family默认关闭，真实权限尚未探测；YC独立权限未知且真实type/code过滤需验证。
- 候选沿用旧records投影、旧SQL/游标/任务身份；新CB发现独立bond_extra_convertibles，报告end_date与评级ann_date分开，YC0/1请求身份不合并，不把101↔1001.CB当已验证别名，不省掉报价22隐藏字段。
- 正在准备最大23真实请求的probe与全列固定verifier；逐API启用helper由原审核版缩为单family，8个隔离负例通过，含隐藏字段缺失、YC类型未验、饱和、过滤、缺对照、重复请求和权限阻断。所有脚本齐备才部署，不为等脚本暂停生产。
- RRG40于04:34:08Z只读核查2done/38pending；20250930 daily5423与adj_factor5437，共10860来源行、6raw/obs/Parquet文件SHA/全列通过，无空或失败。所查云固定8f9d1c65与Mac41d91a尚未包含新6文件，不能宣称完整窗口离线。报告/tmp/tushare-rrg40-current-evidence.json SHA f91fa69e73a363542cbfdd7628df2ff133c12755e1f85ad2c4976a830c252ac9。
- TDX/KP成员先准备6个实际已存板块的合法code分区探测，父3000行仅下界；保留未知板块/成员全集、第二维、PIT缺口。将2API加入已运行market_sentiment会改变旧交织历史policy，需单独追加scope迁移；本轮不重置旧游标来放行。完整目录/历史/修订/附件范围继续。


## 2026-09-09 13:12 六个债券接口启用与并行验收

- 092dedf已部署master/GitHub/cloud，200采集API/206读取dataset；4745文件、source_digest36ff07ee8b5780454240fde6cebbc080a74badc1456a807c99ee1ba55267c048。仅采集消费者04:46:07Z暂停接新任务，04:47:42Z自然排空，04:51:06Z恢复；文档和US消费者保留。四服务健康检查通过。
- bond8初次11 HTTP/12结果遗漏了可用CB种子；有限发现修复优先已验cross6原文，同epoch补9请求/382行，旧12观察/对象均未重抓，累计20调用/21结果。19项隔离测试通过。云/Mac固定0a5af2a6全部原文、70已知字段、61相关文件及reader对账通过，共同证据一致；YC独立权限拒绝；bc_otcqt bulk2000保护阈值，精确09/04范围却含09/07—09/09三行，保持饱和和过滤阻断。
- top10_cb_holders、cb_rating、repo_daily、bond_blk、bond_blk_detail、bc_bestotcqt六接口已按验收启用；新增500近期+500历史任务，旧无关配置/规划/请求门控保持。启用无上游调用，审计validation/bond8-enable-20260909T050941Z-b53f05c7.json，发布data-6ef5044ed2d8d677129d4d96d2d751709e1fd9c97c9763a038998ba055268039。有限样本和启用不代表完整历史。
- TDX/KP六个合法成员分片真实985行，11字段/27相关文件云/Mac固定验收相同（完整报告同SHA17f5dafdb03172fede12f6a914e68940040beeefc9b6c3bd8660e69ccfd9785c）。父已见子集不缺，未知全集、第二维、PIT及追加scope迁移8项缺口保留；两个成员API仍不启用，不重置旧历史策略。
- 标准Mac mirror固定data-0a5af2a613b00f3c8cf088662215614fb1d56ba38c162f480a270634370103a1已校验267257文件，新增6798；bond Mac报告SHA78a547f9a16783e5ecae4b82d54b080328b5564b074143b8eab269fb7a9e19a0。此验收不声称Mac已追平后续启用版。证据归档validation/intake-batch-20260909T044559Z。
- RRG40于05:01:54Z为14 done/26 pending，75992行、空/失败0；当时e79fc1f4云/Mac已含8项，另外6已落盘。未重复扫描后续当前数，完整日历/成员PIT/ETF映射仍待验收。RRG优先窗口、其他接口开发、固定验收和镜像并行，不等全目录历史结束。
- 下一calendar/factor5纯候选5aa26e1（26字段）及目录解析候选f024021（12相关测试）已独立推送，未合入或部署。后者只修复schema表头并定点486输出13→真实4，保留数字起首字段和全部源HTML证据。263基线+13发现及完整历史、修订、附件范围不缩减。


## 2026-09-09 13:33 Calendar/factor5与成员追加scope候选

- 父基线79f4498整合纯5aa26e1→1983599、parser f024021→d8ed13b、运行dcb2c3e→115e4af及member alias06acf3a→dd7279d。候选205采集API/211读取dataset，新两family与market_members scope均默认关闭；生产仍200，未把候选记成接入完成。
- 全263官方页面重新只读获取，HTML SHA全部与目录存档一致。共享parser除校验名称表头，还排除hm_list同名示例表；新增四页目录修正删除28个伪输入参数、7个伪输出字段，全部为原文枚举说明值；原文/枚举证据保留。完整证据/tmp/tushare-full-schema-audit-20260909/final-report.json SHA db6ffbb0e6c8588d017ab4b9f43338d4344206221f2e78bdf8706df231163ab2，版本化摘要tushare-catalog-schema-full-audit.evidence.json。既有因子486九类别误列修复保留。
- 7份旧测试19处YYYYMMDD日期解析改为等价strptime，保持覆盖断言；194纯合同测试先通过，联合后实际Python3.10完整603 tests/31.687秒通过。17项calendar/factor helper父基线测试1.617秒通过；第一次以unittest绝对模块路径启动失败未执行测试，改为直接脚本后通过，日志独立保存。
- 日历18列与因子8列完整请求，允许源前值/预测等非标识空值但不豁免缺列。factor_list无源日期，factor_value只从真实列表资产/名称规划；合法code-only样本读取支持，列表缺失时名称/资产映射仍阻断自动启用。有限probe正常16/fallback13、硬18请求/120秒，仍待生产权限。
- market_members使用独立APPEND_PLANNERS进入自动规划，合同/消费group仍market_sentiment，旧PLANNERS消费组与份额不变；依赖原组启用并禁止旧scope同时含成员API。新scope保留bulk发现与已观察板块逐码历史，来源新增通过原冻结快照/refresh追赶，默认关闭、历史起点须显式，全集/第二维/PIT仍缺口。启用helper准备中，未修改旧游标。
- 只读云端检查采集与文档worker healthy，SSD492G/已用220G/可用248G；本轮无扩容或消费者暂停。下一历史分钟7纯合同并行准备，非本批生产范围。


## 2026-09-09 14:12 Calendar/factor样本、成员scope与并行接续

- f627b89已部署到master/GitHub/cloud，205采集接口/211读取dataset；4778源文件哈希一致。采集消费者05:43:51Z自然排空，仅重启quantmind+tushare-worker，05:49:53Z恢复；约6分钟窗口，文档和普通US任务保留。四内部服务健康检查exit0。部署原始证据已归档validation/intake-batch-20260909T053533Z。
- calendar/factor5实际12次请求：eco_cal两日期日/范围共300行（未来两响应各100满额）、cn_schedule两月与真实title过滤共33行、idx_anns当日空、factor_list拒权、factor_value真实000001.SZ日/范围共390行。全部26已知列请求；非空来源没有缺列。固定cf01版36关联文件、12观察云/Mac核验六共同键一致，去重eco150、日程31、因子值195行，0上游查询。
- cn_schedule已实际启用并发布cb015198版：近期3+历史439个新任务；48条无关规划状态与成员scope保持。history规划done只表示月份枚举结束，442个待采集任务不等于全历史完成。enable收据calendar-factor5-enable-20260909T060700Z-a6859bfd.json，SHA7c25142c6c1b5542321eecf95e6aad12f65a6b506d3ce9880e193c2fd558f353。其余4API暂未自动启用，非阻塞缺口继续推进。
- 成员market_members追加scope已启用并发布cf01版，新增1000任务身份核验、46条旧规划提交时保持。06:04:32Z两API均已由自动规划续跑，旧market_sentiment同policy继续前进。第一条bulk仍满额并进入split_pending；未知板块全集、成员第二维、历史PIT保留。receipt member-scope-enable-20260909T055627Z-7242ccfa.json及事后摘要已存证。
- 标准Mac镜像已验证33a0版289769文件，本轮新增6652。随后同cf01历史固定版离线查询通过，不能把较新云cb015198启用版误称已镜像。RRG40于06:04附近为36done/4pending、195339来源行，40任务身份与优先级0异常；本轮该检查不冒充完整raw/Parquet/全窗口验收。
- 下一步并行：分钟7纯合同bd197c8已合入父候选de8e8eb，58字段/5频率，父Python3.10八测试0.007秒通过，runtime准备中，未部署/请求；因子值转向显式code-only规划，复用已验证195行证据，不为缺factor_list而放弃可用值，也不伪造STK目录/公式；发现缓存完成固定小实验但尚未上线，继续测完整本地工作集和实际workerRSS。
- 全263基线+13发现、全部历史/修订/原文附件与RRG/PIT准入仍未完成。协调记录和实际receipt是接续依据，未完成工作不因单批通过而删除。


## 2026-09-09 14:29 下一分钟/因子候选与RRG40采集完成

- 本批已验收台账与21条接续记录合入master/GitHub876386e；双端handoff首轮仅因源同步尚未追平拒绝，随后4793文件逐项diff为空才重试成功，digest96141b0cbc2bf08cd14646ce42b6158be660c44b9a36669e78936970cbb5c4cf，云Git同876386e；未重启服务。证据/tmp/calendar-member-closure-handoff-retry.json。
- 父候选792db04（text def23cb）+17b6c88（structured96ec42e）：factor_value显式code_only、实际stock依赖与mode签名；分钟7登记及秒级reader/namespace/freq/来源发现接线。候选212采集接口/218读取dataset，生产仍205/211、分钟默认关闭。父实际Python3.10完整623 tests/32.462秒通过（/tmp/tushare-minute-factor-parent-full310.log），尚未同步新运行代码或启用。
- 一次实际factor_value范围请求000001.SZ/20260901–04返回780行，前3日期真实存在，末日195行与原12样本中0904逐列多重集相等、缺列/过滤错误0。原12报告SHA保持，独立报告validation/factor-value-range-probe.json；本次未发布，固定reader和月窗仍未验证。helper dcd9f77f…026a851，父17tests通过，原共享锁等135.953秒后执行1调用，未暂停消费者或改变频控。
- RRG40只读postcheck现已40done/0pending、40sample_ok、217026来源行、40身份/优先级0issue；当前指针c9736769…4a266。完整40原文/Parquet/同版reader/as_of及Mac闭包已转structured优先验收，未把队列完成当成完整RRG输入/策略准入。
- 缓存扩展实验在固定Mac33a0全部80517观察范围选18026发现来源：64MiB缓存贡献50.97MiB、热6.519→3.809秒；32MiB有界热6.534→4.788秒，两者ID SHA一致。镜像观察集合不是liveDB来源全集，云worker历史峰接近1GiB；仍不部署缓存。/tmp/tushare-compact-full/handoff.md保留边界与失败测量。
- 并行待交：分钟7实际来源+有限helper；仅factor_value的code_only启用helper；eco/idx有限分片/宽窗探测helper。eco旧raw.country混有economic_activity等类别字符串，语义待核、不改原文。263+13和全部历史/修订/附件/PIT目标不变。

## 2026-09-09 15:10 因子启用、分钟权限与日历补证

- 5d442d3已通过两端4805源文件核对并部署；quantmind/tushare-worker重启exit0，四内部服务健康检查exit0，06:53:36Z实际采集任务和队列已恢复。文档队列与既有US任务保留，Mac客户端同步新代码、原900秒镜像周期保持。父623全套测试不代表212接口均有权限或全历史。
- factor_value code_only已启用，首批近期500+历史500任务入队，6225个已观察源股票冻结。只改三个因子配置键，其他配置/任务及未完成游标保持；精准1000ID与两游标后验收通过。receipt factor-value-code-enable-20260909T065854Z-b78e5541.json，SHA3d6adb90e82312adfd820c9f889c2058e24b5725ecaec3fdea3bb71cca4443f4；固定c71d0dab…3fb26。该时点1000均pending，不能报已下载。新helper父14tests通过；提交后发布/收据失败不回滚已提交任务，重复启用拒绝。
- ca7c因子范围780行经独立原始响应验证：0901/02/03/04各195，0902–03共390，默认/显式日期轴十次查询全列/身份一致。月窗仍未实测；接下来应验证合法月窗及保留已有进度的范围规划，避免6225代码逐日全历史请求过多，不以缩小历史范围提速。
- 历史分钟7实际8次请求：stk_mins日窗241行、8列齐全；6其他分钟API权限拒绝；股票实际秒窗控制触发1请求/60秒限频，已持久记录quota。固定读取核241行及11:30:00默认/显式秒轴各1行。分钟仍不自动启用；独立的单请求后续控制正在准备，原8请求报告不重写、不重抓日窗，不用积分推独立权限。
- calendar-gap实际8请求：美国21/欧元区5/德国5行各日/范围对照；idx_anns范围259行和源实际20260102单日1行。固定源全列、去重、范围控制均通过；经济日历去重151行（含原样本）、指数259行。保留eco全市场饱和/国家类别语义两项缺口，idx范围补证不等于已启用或附件/历史全集完成。下一步单独追加已验idx scope，保留现有cn_schedule/factor规划，不复用会重配其他family的旧启用脚本。
- 固定data-1f3dfb00ef633aa0a8bd408101dd7303c36d9bd8b03c3eb13da0226e6d2c6ea6正常发布21.037秒/0HTTP；Mac镜像315383文件、5888新增通过。分钟与calendar两组云/Mac同版共同证据逐键相等（分别33/2已解释或未验证缺口），源/Parquet/本地reader核验不请求上游。
- RRG40 ca7c完整云/Mac120文件217026行、40全列+40as_of零差异。另已证240日历骨架及必要股价/复权/当前权重字段齐备；5394当日与5337完整20日个股输入存在。67缺价端点按已存官方停牌语义解释，剩208端点/48股精确清单，20260831仅2端点优先补证。历史成员known_at、权重口径、ETF及研究case仍blocked_data。
- 全范围差集重新按命名接口核对：234命名并集减212注册=22，含19只读、1 SDK pro_bar、2 excluded_mutation；无名/失效/分类页及3 unresolved mentions继续保留。融资历史slb_sec/slb_sec_detail/slb_len_mm与开户历史stk_account/stk_account_old共34字段在独立worktree并行实现，尚未生产采样/部署。
- 本批不可变证据目录/data/tushare/validation/intake-batch-20260909T065700Z；清单/tmp/minute-factor-preparation-archive.json与/tmp/minute-calendar-closure-archive.json，双端核对/tmp/minute-calendar-dual-fixed-compare.json。263基线+13发现、全部历史/修订/正文附件与消费端/RRG准入仍未完成。

## 2026-09-09 22:06 月窗口、指数公告与历史接口候选

- 股票分钟额外一次窄窗真实返回40203、2次/天，已持久记录；与原1次/分钟观察分开保留，不再追加当天探测。原241行不重抓。固定1d96532云/Mac核查完全同SHA93ed0fe3a8a13a511d0624dbdd8dd7224c0be76e1a179cd76bb553608e514af7，状态unavailable_no_success_claim；本次没有新分钟数据。
- factor_value真实两次调用：000001.SZ/20260801–31返回4340行、21个交易日期；只从实际返回日期选0817独立控制，212行。均4列齐全、未触6000上限。固定4d55e6bd月/日默认及显式日期轴四次读取与原始响应逐列相等，云/Mac报告完全同SHA948fd93e2fe674f4d462fb867b5438efaa0dcba5d871551a254a9b4d12f28b98。只证明这一个股票/月窗口，不证明全部因子、日历、历史或PIT；月规划迁移尚未实现，原每日回填继续。
- idx_anns已实际追加启用，只有calendar_extra_apis从[cn_schedule]改为[cn_schedule,idx_anns]。新近期7、历史250，共257请求，事后全部身份核验一致、当时pending；历史游标仍未完成，原任务/其他配置保留。receipt idx-anns-append-enable-20260909.json SHAdea99b503a92fd51e4df0277803ad8e2566783b6c153c906b1e55f529ad9eb73；启用0上游请求，发布4d55e6bd。既有eco两项语义/饱和缺口不豁免、不启用。
- 标准Mac镜像4d55e6bd已完成378780文件校验、2040新增。第一次pointer_fetch SSH退出255，终止已确认；SSH只读复查成功后重试通过，旧固定CURRENT未被失败覆盖。分钟前一轮1d96532镜像376739文件、5894新增也完成。
- 父候选融资3运行时845efcd及实际起点签名修复745e0a6，父45相关测试通过。开户2纯0d251f1、运行时62aa0e9，父60相关测试3.577秒通过，旧周期原文保留且本地支持闭区间相交/端点过滤，未知周期明确gap不丢数据。合计候选217采集API/223读取dataset，尚未主树发布，生产仍212/218。融资3有限真实探测及开户控制探测在准备，默认off不能报生产采样完成。
- 云端13:50:37Z一轮SoftTimeLimitExceeded：160秒预算中planning66.556秒、identifiers60.030秒、acquire78.976秒，下一轮继续。诊断发现每tick重解析历史body且每tick新Pipeline；只加SQL索引不能解决。独立派生磁盘缓存候选正在实施，不改正式schema/原始对象/来源集合，尚未启用；不把合成基准外推为生产加速。
- 本批证据归档/data/tushare/validation/intake-batch-20260909T133800Z，父测试、真实报告、固定核查、追加收据及postcheck均有不可变SHA。实时剩余8接口纯合同接续；发现stk_auction官方已支持历史，按原文保留历史义务，新增邻接API另列，范围不以原目录数量封顶。完整目标未完成。

## 2026-09-09 22:38 融资/开户离线闭包与月规划合入

- 融资历史3接口实际探测共3322来源行：slb_sec2254、slb_sec_detail937、slb_len_mm131；20个已知字段、原始对象、观测、Parquet及固定reader逐列通过。开户stk_account的2018年范围51行与实际20181228单日1行逐列重合；weekly_hold和weekly_trade的源空值原样保留。stk_account_old返回供应商api_error40101，不改写成无数据或权限结论；开户停止更新范围、旧周期轴及PIT仍是缺口。
- 两组都固定在data-fc6747298150d36345c840839310d1819d977536a0253d17ecc9550d1db675c2。标准Mac镜像新增356、共380050文件校验通过；融资云/Mac完整验收JSON同SHA e506c27db21027fa9ba178c1872b1a8a8be541d8ab9f9eb98cb71594d8ade7f3，开户16个业务/完整性键一致，仅elapsed_seconds不同。验收0上游调用，不把单个官方样例日扩称完整历史。证据归档/data/tushare/validation/intake-batch-20260909T141000Z。
- 显式code_only月历史规划84590f6已合入/push master并通过双端handoff（4859文件，digest27f8d3978818decf4b2a085d2e5d1be62b3742d8aeebc7baf720d6b353a1549b）。默认/显式daily的旧policy保持；月模式单股票19900101起历史请求从13394降至441、近期7日仍逐日，达到6000仍按现有合法日期拆分。父级28项相关测试通过；未切生产配置，旧非零daily游标的安全迁移仍需实现，不能把代码合入计作提速生效。
- 14:29:38Z最近publish_only批170.006秒超时，retain_previous95.166秒、serialize_manifest20.675秒、coverage_and_closure19.598秒；CURRENT同时正常推进，不能称采集或所有发布停止。只读诊断确认前版大清单存在重复读/hash/decode及完整files映射复制，但临时fixture不能解释云端全部95秒；最小优化候选继续细分锁等待并复用已校验前版，不删除历史或降低完整性。
- 固定版当时覆盖状态done50967、empty43894、pending2119354，动态规划数不是最终分母或数据行数。云端盘可用约250.98GB。实时8、相邻回放2、自选组合2及发现磁盘缓存仍为候选/审查项，未生产启用；263基线+13发现及后续邻接发现继续扩展，完整历史、修订、附件、PIT和RRG剩余缺口仍未完成。

## 2026-09-10 00:37 权限分层限速完成灰度并保留500档

- `aad9310`已合入/push `master`并部署云端；双端4916源文件逐项摘要一致，source digest `9263785e0458505ed72697a7434f7802ab06ccf5de0bc5ea78e6480d356523f4`。新增227接口的机器可读频次证据及分类细化：147明确常规、3个10000分特色、5个不确定；运行时只使用显式allowlist，不从补集推断。专项35项、完整Tushare 777项Python3.10测试及Ruff通过。
- 配置记录用户声明的10100积分分笔与日期：2000分在2026-12-05北京时间00:00保守失效后预计8100，90天提醒已进入`pipeline-status.json`；8000分及九项已购独立权限统一记录到2027-09-08。报告只存积分、日期和接口族，不含Token、订单或付款材料。147常规在8100仍为500；3个特色回合同30/30/50并要求复核；`hm_detail`届时报告10000门槛未满足；`factor_value`继续按独立未知频次/合同30保守，不假定500。
- 云端按300→400→500逐级执行，每级先dry-run、只改4个授权配置键、再由上一档`passed`文件的SHA和当前配置SHA门控。最终生产配置`rate_policy=tiered_v1`、全局硬上限500、rollout账户档500，配置SHA `2600c2b5f3446bd1b9fba8a839c494a23a65091ca283483f065166f38356d72c`。新闻400、公告/问答/政策/已购研报500、央行报告200、特色300、叶子页/合同/已观察冷却及显式低上限仍取更严值。
- `cyq_perf`本地耐久日额度在每次HTTP前预留：当前10100为200000/北京时间自然日，预计8100后为20000；部署日2026-09-10使用activation guard，不把启用前未知调用量当零。账本`daily-quota.sqlite`只属于云端当前root，不发布、不镜像；失败/中断请求不返还，时钟回拨或账本损坏保守失败。不能把本账本称为供应商全账户用量。
- 300档三条真实采集共207请求、全200，连续中位间隔0.200–0.201秒，对应298.5–300/min；400档两条共133请求、全200，连续中位382.2/392.2/min，无冷却样本完整网络段313.5/min；500档两条共100请求、全200，连续中位间隔0.121秒、约495.9/min，完整网络段275.9/312.2/min。三档均无HTTP429或已记录供应商频率错误；不能把档位值当持续吞吐，响应时延和接口冷却仍降低整体速度。
- 不可覆盖验收分别为`/data/tushare/validation/rate-rollout/{300,400,500}.acceptance.json`，SHA依次`5e80adeb9e4fce6c1ac9768a589d6315c3d1f4c41e51db82e7a411108236909d`、`221d88aec8c0a4f97dbcc6eab6abfba2f7ef7f16b43d4f87533a95087f133c26`、`dcc7abb4414a7e119ff84799df55b4fbc7e726285921f5b02754e4e1f04f14d9`。quantmind/tushare-worker均healthy、无OOM或意外重启；最终500档保留，采集调度继续。
- 现存主瓶颈没有被限速改动掩盖：采集任务仍常在约78–81秒规划后，于160秒软超时期间反复解析约1GB历史标识符JSON，另有约60秒已观察API冷却；需单独优化派生标识符索引/缓存并保持原始对象、任务和历史义务。本轮灰度期间publish-only仍成功生成`data-413b5869…`和`data-703b5dc1…`固定版本。
- 发布保留优化已由真实发布验证；factor_value历史已切月窗且1000月任务入队、旧87577日任务/尝试不删；实时10接口运行时已合入但默认关闭，有限probe待权限安全窗口；冻结命名范围236中227可读、9未登记继续保留。Mac客户端限速/日额度模块哈希与源码一致；两次pointer_fetch SSH瞬断后按原安全流程重试，固定`data-703b5dc1…`共394321文件、0新增下载完成校验，覆盖done53064/empty46404/pending2270024/permission_blocked1165/quality172/blocked428/split_pending1442/resolved490，旧完整版本未被失败覆盖。

## 2026-09-10 01:19 规划与采集分批生产启用

- `f01f870`把实时十接口有限probe和固定版离线验收工具纳入仓库，默认dry-run、最多15请求/120秒，复用同一账户/API门控、生产锁和日额度；专项24项及Ruff通过。本轮未执行实时probe、未开实时生产范围。跨日后暴露的旧日额度fixture已在`5b488f3`固定测试墙钟，21项重新通过，不改运行时。
- `aae3bc8`将可选`planning_interval_seconds`纳入主线：默认0严格保留旧路径；正值要求已有正发布周期。生产设900秒后，发布到期优先独立`publish_only`，规划到期独立执行`initialize+plan_extended`并在全部成功后写持久配置指纹检查点，其余批次跳过这两个重阶段直接采集；失败、配置变化和时钟回拨不会伪造新检查点或重置各family游标。9项专项、发布/时序回归及完整810项Tushare测试45.944秒通过，Ruff通过。
- 双端源码/Git已对齐`aae3bc8`，4928文件digest `beae4b9dd83cc0b6ddd607fa3e909f13b9aacc05a9a3d6dad77e69362032813c`。只在采集worker排空后把配置从SHA `2600c2b5f3446bd1b9fba8a839c494a23a65091ca283483f065166f38356d72c`切到`2ccb29fd53ab92aabcbebe087231d5d2e955c407b5ab5b18353c099dffb4f449`，新增唯一业务键`planning_interval_seconds=900`；500档分层限速及900秒发布周期保持。准备/提交收据SHA为`5c42d771…`/`e18ed40e…`，采集worker重启后healthy、restart0、OOM0。
- 首个真实规划批`bf536d45…`成功：总86.034秒，其中planning78.542、identifiers71.271，0上游请求，持久检查点下次到期17:24:44Z。真实发布批`56ae4767…`成功69.274秒，生成固定版`data-0e961a88…`。两个后续纯采集批`4d3f9585…`/`3215f989…`均成功，分别44/95请求，run窗口89.938/89.981秒、acquire阶段93.150/92.735秒，总任务121.631/106.159秒；无规划/初始化重扫、无确认429或供应商频率错误。
- 仍有一条纯采集批`abf6b9d6…`在acquire阶段157.201秒后触发160秒soft limit，说明API冷却、响应/末次归一化及文档登记仍会造成尾延迟；本次没有调大软硬超时或资源。44/95是不同任务组合的运营样本，不能宣称持续500rpm；500档连续请求约495.9rpm的单独验收仍沿用上一节证据。不可覆盖生产验收`/data/tushare/validation/planning-cadence/900.acceptance.json`，SHA `2ca27f7f8de77c98e383c43a68f4c8bad93cc18736892272930df734797242ad`。
- 全量发现磁盘缓存候选13轮输出SHA完全一致，但普通cold/early-warm约33.9–35.8秒无收益；23.065秒full-warm要先额外priming70.911秒，且1GiB cgroup仍触顶。候选安全边界在分支`codex/tushare-discovery-cache-current-review`提交`35bb612`，生产保持关闭；不以热缓存合成结果代替规划分批的真实验收。900秒规划会把新增标的/范围发现最多延后到下次规划，并降低planner游标推进频率；当前约235万pending足够消费，待积压显著下降或启用短TTL实时范围前必须重审周期。
- Mac镜像随后原子切换到固定版`data-0e961a88…`，清单397173文件，覆盖done53411/empty46698/pending2365922/permission_blocked1165/quality174/blocked436/split_pending1450/resolved490/deferred_legacy_period_plan9802，`rrg_status=blocked_data`；旧完整版本保留。之后云端实时库继续推进到done53756/empty46997/attempts104831，并由新规划扩展到pending2453446；采集、附件任务均active。固定版与实时库读数时间不同，不能直接混合。

## 2026-09-10 09:53 薪酬规划恢复与文档登记分批上线

- `f71d8ab`把附件登记改为默认5秒/500条、每事务最多100条，并用既有`scheduler_state`保存精确attempt/row偏移；顺序固定为documents提交后再提交pipeline游标，锁忙、预算耗尽或游标提交失败均可通过确定性引用ID重放。`15e6722`只在stock_context消费边界隔离非法股票叶；原`stk_managers`中的`X20720.SZ`、原文、发现库存和父任务全部保留，并记录独立coverage gap。两项经合并后851项Tushare Python3.10回归通过、跳过5项；`8193d14`已推送master并通过Mac→云端handoff，5900文件、source digest `a8acee66d0751ab6d3be8ab85253e770da3ad495bf31a3e47d69e41dd801e74e`。
- 只排空并重启`tushare-worker`和`tushare-document-worker`；其他市场、研究、主服务未动。两个新容器均healthy、OOM false、restart0，并在容器内确认加载新函数签名。部署后文档worker两批真实任务成功，分别约92.04秒/47件和91.59秒/79件；观察窗口未再见`database is locked`。
- 首个新代码规划批`1844c1fa…`成功、0请求、137.55秒；stock_context父能力从validation_blocked恢复为validation_passed，异常库存另记1条coverage_unverified，合法股票6295个。该批执行时已经观察到的54个合法stk_rewards股票/报告期组合全部入队，history规划新增54；原非法值未进入请求。随后正常采集产生更多薪酬原文，后置收据时有效观察组合已增至218，而计划仍为54；这是900秒规划 cadence 的新发现等待窗口，收据明确`all_actual_pairs_planned=false`，不能把先前54扩称当前全集。
- 正常采集`2df4252c…`成功，360请求、acquire83.31秒、整任务105.41秒；附件登记0.918秒处理500行并保存偏移402。下一任务`1b5697a0…`从同一attempt续到902，再处理500行、1.081秒；没有重扫已提交行。对应独立文档任务`5ba2680a…`成功处理79件、91.59秒。部署后12分钟日志共448个HTTP200、0个HTTP429、0个供应商频率错误、0个soft timeout；运行时仍为tiered_v1、账户档500、batch360/90秒、规划/发布各900秒。
- 发布到期批`fc0c089c…`成功并原子切到`data-0c8bff9f9d09b952da909fad391bf2604e2dcf60ab78afeca8804d5c065b4671`，但耗时151.88秒，仍接近160秒限制；此前已有多次publish_only超时。三阶段候选`bbc818a`证明崩溃恢复和manifest字节一致，却未降低最长单阶段且总耗时更长，因此仅保留`codex/tushare-publication-checkpoint`审查分支，未合入master、未启用生产，也未提高超时。
- 标准Mac镜像对一次manifest_transfer rsync30瞬时失败重试后成功，先推进到`data-ac275…`；随后LaunchAgent下一轮增量追平云端`data-0c8bff9f9d09b952da909fad391bf2604e2dcf60ab78afeca8804d5c065b4671`，共验证517286文件、最近退出码0。失败期间旧CURRENT始终保留，本地没有访问Tushare重抓存量。云端Tushare目录74G，磁盘剩余160G；100GiB自动停采保护仍启用，扩容继续按阈值触发。
- 不可覆盖生产收据`/data/tushare/validation/stock-context-document-budget-20260910T014826Z/acceptance.json`，5163字节，SHA256 `854f21a97f43eac4933e53d644a1d921d7fdbe73886b9b15ecc38c05263c01b4`。收据保留上述4个任务的脱敏结果、配置白名单、能力状态、文档断点和固定版身份，不含Token/订单。完整历史、持续新增组合下一轮规划、发布160秒尾延迟、百万附件下载解析、RRG成员PIT/ETF/研究准入仍未完成。

## 2026-09-10 10:44 薪酬组合快追与发布提交恢复

- 生产继续运行后，`stk_rewards`有效观察组合从218增长到524；原stock_context冻结快照至少还需29个900秒规划轮、约7小时15分才会刷新，不能描述成下一轮追平。`4e4b58d`增加独立`history:stock_rewards_periods`有限追加范围，沿用原history任务ID去重、每轮最多500且不重置原recent/history游标；`9a6685c`把该范围放到planner循环首位，其余planner相对顺序不变。第一次真实规划重试把计划54推进到500；部署排序修复后，无上游调用的固定快照补齐在78.885秒内再新增24，断点`offset=524/done=1`。独立只读核验实际524、计划524、`all_actual_pairs_planned=true`；非法`X20720.SZ`仍仅保留为原文/coverage gap。
- `1a01997`用CPython同一C编码器分块直接写私有临时清单并同步计算SHA，保持清单字节、fsync、SHA目录和原子CURRENT语义。约102MB代表性清单的18个独立Python3.10进程对照中，中文最长完整编码/哈希/写盘下降12.0%，峰值RSS约736.9→443.8MB；非BMP最长下降13.3%，峰值约956.8→459.9MB；ASCII最长仅下降3.1%，因此不据此承诺整个生产发布必低于160秒。
- 新代码首个真实publish-only仍在160秒软超时，但已先把CURRENT原子切到`data-e201969a…`，旧`publish_success_at`尚未提交；下一次幂等重试140.155秒成功并切到`data-c59d2208…`、写入检查点，采集恢复。`a22f107`增加持久`publish_intent:<精确release_id>`：仅在完整manifest已写/校验后、CURRENT切换前记录；下次先验证CURRENT身份完全匹配才补记成功，swap前失败、坏manifest、mtime或时钟回拨均不误推进。旧无intent版本不被追认。
- 最终联合Python3.10 Tushare回归877项通过、skipped5，Ruff和diff check通过；`master`、GitHub与云端统一为`a22f1079c6f75b1a2f1d494a2e8078dc3382db2e`，5917源码文件digest `b33c9bf96e8ed6a8210242fffc221ff81fc239a05811e85c8415db00002ecd71`。只重建已排空的`tushare-worker`；文档、研究、其他市场服务未重启，500rpm分层限速、900秒周期及160秒软上限不变。
- 补齐收据`/data/tushare/validation/stock-context-document-budget-20260910T014826Z/reward-period-fast-append.json`，文件SHA256 `d9acfb2a44acccae931609a496e33964630b3cbbef95d7e6a5384bac287eb798`；此前人工同tick规划收据`manual-publish.json`实际记录的是planning-only 104.755秒/0请求，文件SHA `87b393a36f5aa721ecf3ad3bf5fc60b710175a00ef732aa145482c416e26e78f`，名称保留以免覆盖证据。
- 附件只读20分钟样本为待处理约105.6万、净新增parsed166（约498件/小时）；冻结队列算术约88—97天，实际队列仍增长，不能作为全量完成ETA。现有2路下载+1路解析已经启用；一次`_finish_document`写锁失败后恢复，领取2条的查询约0.398秒，尚不足以把90秒任务尾延迟归因给排序或据此增加消费者。当前可用约158GiB、距100GiB停采线约58GiB。
- 标准Mac镜像已原子追到`data-d1524977…`、522363文件；更新的`data-c59d2208…`仍按900秒固定版协议等待下一轮。完整历史、持续新增组合后续追加、发布总时长、附件下载解析、RRG成员PIT/ETF/研究准入继续未完成。

## 2026-09-10 11:14 新增任务预算修复与最终生产验收

- 首版薪酬追加在生产发现一个预算语义缺口：刷新快照时，前500个已存在任务也消耗500条预算，导致实际624个组合时只计划524个。`3a69fe15`把`history:stock_rewards_periods`这一内部追加范围改为仅按新插入任务扣减500条预算；已存在任务仍受扫描数和时间边界约束，其他family预算语义不变。624个源组合/524个既有任务可在一轮新增100并完成，超过500个新任务时仍分轮续跑。
- 最终Python3.10 Tushare回归881项通过、skipped5，Ruff和diff check通过；`master`、GitHub及云端源码统一到`3a69fe159fea94ca967fa7a933fad77a9b8c21d5`，5919文件，content digest `7b3022af9bba2870e11878ab92b3745a60e3e7befd5849b15b4000f413084ae9`。只在采集worker自然排空后重启该worker，文档、研究及其他市场服务未重启。
- 两次0上游请求的固定快照规划分别将观察组合524→624（新增100，82.733秒）及624→737（新增113，84.518秒）；后一轮属于完成后发现新组合的正常快照刷新。2026-09-10T03:08:01Z独立只读复核actual737、planned737、`all_actual_pairs_planned=true`，追加断点offset737/done1。对应不可覆盖收据`reward-period-new-budget.json` SHA `2fcd3f0a35b0feba6050cb01cffa764db330aaf0cbc82e3c345c8c62e072fa63`、`reward-period-new-budget-refresh.json` SHA `ac1afd8c86612d557062cb1855ed715adeb2117b2f7c7b1c9d39d38edff14bc3`，独立报告SHA `22dfb7c3335c7f999b5dcb867b13a1b2bec5a100b4c6911ff39a66934d484847`。这证明该固定观察快照已全计划；后续新采集组合仍由同一有界追加范围继续发现和补齐。
- 最终真实自动publish-only任务`2cdb1b56-fbe6-4015-b2ed-e730aaf1bc1e`成功，0请求、144.088秒，在160秒软上限内原子切到`data-2c8715f9920400555ccab3f739c982938cb127f72db1a1c6c0bb18378b6f1662`，`publish_success_at`同步更新且待恢复intent为0。精确release intent恢复逻辑已经部署，用于今后CURRENT已切换而检查点尚未提交的崩溃窗口；本次成功任务未触发恢复路径。
- 最终运行收据`runtime-observation-final.json` SHA `b83de442ce035cf1e34b1c6f7945d4ab0db24d2fa42f2adc2f5b80c47de1d25d`。11:00后的最终部署窗口内两个采集任务成功、失败0、soft timeout0、HTTP429及供应商频率错误0；该窗口任务均为0上游请求，500rpm的真实网络灰度证据仍采用前述300→400→500验收。
- 权限补充收据`entitlement-observation.json` SHA `3157a8e44a48104cb6765e79a0324bb9bfcfe2fb8768616aa7b3bce11ad2b641`直接读取生产`policy_report`的脱敏字段：用户声明10100分，2026-12-05的2000分到期后推导为8100分，当前触发90天提醒；独立权限到期日2027-09-08。收据明确标记用户声明、非供应商二次核验，不含Token或订单凭据。
- 最终只读快照中文档引用1362606，pending1059185、parsed14750、blocked2609、retry5；短窗仍约498 parsed/小时，队列还在增长，因此不提供有限完成日期。云盘总约492GiB、已用约310GiB、可用约156.79GiB，100GiB停采保护保留；Tushare目录约76G。附件分阶段耗时、长期写锁、百万队列索引以及完整历史/RRG成员PIT/ETF仍是开放项，不阻塞结构化数据和固定版本继续采集、发布、镜像。
- Mac LaunchAgent第82轮退出0，标准镜像已原子追平同一`data-2c8715f…`，本地manifest列出529362个文件，镜像目录当前约65G。失败或下载过程中旧CURRENT不变；研究应固定release ID离线读取，新镜像不会自动替换正在运行的研究输入，也不会从Mac回写云端权威数据。

## 2026-09-10 11:55 实时权限闭环、文档索引 v2 与 RRG 数据桥生产验收

- 实时十接口在同一生产锁、现有分层门控和真实固定种子下完成一次有限探测：15个计划样本只产生10次上游调用；`stk_auction`首个精确请求拒权后，同API另外5种参数按规则停止，`rt_etf_sz_iopv`、`rt_idx_k`、`rt_idx_min`、`rt_sw_k`、`rt_fut_min`、`rt_k`、`rt_etf_k`、`rt_idx_min_daily`、`rt_fut_min_daily`各自一次均为`permission_denied`。未改配置、未启用、未推断任何同族接口。探测SHA `62ee99ff5b802b29d05a019ad8e8f40bca106f18071c21b40f02caad2f1a93a9`；原文和observations发布到固定版`data-95fde4b44d540739be6f42f622c8ef331a6e565833f213b36202308e8dd71f1b`。
- 云端和Mac都用固定版离线复核为`verified_with_gaps`，0上游调用、候选启用列表为空、等价SHA `aa1d32970e6c0a507c78c0844ed85d0bb97b1f379ac54bc43c42ef42fdaf2fa2`；两端报告字节SHA同为`f3fb4f999fb11fc677d7b1130c34ffd8e29ce61c4b52b2f0db3f96f212ab8b50`。Mac第84轮原子追平该固定版，共533967文件。逐API台账已关联精确参数、object/observation及固定版证据；两个邻接回放接口继续单列，不改变263页基线。
- 文档领取v2部署前自然排空采集与文档队列，并以SQLite在线backup保留1,447,735,296字节恢复点，完整性`ok`、SHA `ccd423f4efc7c8aa0f37379be32e495196cf142f58aef86f84aa4625199b216e`。生产迁移把`document_claim_meta`从1升到2，新增`documents(id) WHERE download_status='pending'` partial index；即时复核迁移前后均为1,082,560行、claim为0、完整性`ok`，数据库增加约79.3MB。首版收据误把恢复采集后的新增行用于迁移比较，后续收据均未覆盖旧文件；最终`acceptance-v3.json`以SHA `22da2d21c2de2f8636beafc9e56a3c98d09484ecb15ece1dbf260a1fb32a8e89`逐级supersede并保留完整审计链。
- 两批无审计读锁干扰的真实文档任务分别处理52/82件、耗时91.629/91.572秒。领取DB总耗时为1.398秒/39次和2.287秒/62次，写锁等待0.00103/0.001521秒；finish DB总耗时0.141/0.308秒，下载加解析仍是主耗时。两次生产验收只读事务分别与claim写事务重叠，各报一次`database is locked`；审计读结束后五批已验任务均成功，其中后三批连续处理100/19/37件。索引消除了百万pending排序成本，但SQLite单写者与读事务竞争仍是可观察缺口；后续生产审计需保持短事务或放在排空窗口，不把这些批次外推为长期附件完成率。生产收据目录`/data/tushare/validation/document-claim-v2-20260910T0345Z`。
- 同窗口结构化采集真实任务完成360请求，任务总耗时87.918秒、失败阶段为空；`tiered_v1`、账户上限与灰度档均保持500rpm，末次常规接口门控0.12秒，部署后日志HTTP429及已识别频率错误均为0。两个Tushare worker均healthy；研究、其他市场和主服务未重启。
- `trade_cal`、`ci_daily`、`ci_index_member`、`etf_basic`、`fund_daily`、`fund_adj`、`fund_portfolio`七个原RRG接口已统一进入完整契约、registry、store和镜像安装路径，共62个固定目录字段；生产进程加载成功，已有97489个RRG任务全部请求各自完整字段集。只读验收0上游调用，SHA `f71e99b644004c91399b187a9b19e6d12fffa4c0e5c1870c01406c8be6982115`；既有`schema_gap`、空样本、pending、完整历史和PIT缺口原样保留。
- Mac在`data-95fde4…`上离线生成RRG/ETF接入结构：6740条成员记录但known_at为0；1648个日期候选ETF中1645个有执行日价格和复权，缺`SH511670`、`SH511920`、`SZ159578`且未前填；902个ETF有严格早于signal date的最新披露，执行日PCF为0。报告SHA `9a21f125daf300b87fd8b05bebe7f239dcb69b06b7e59f394b194a7453a5b257`，artifact manifest SHA `a5984bfc96f2ac6c7353ed2f355b001f8207dfe5b1282c5627e88764534f5513`。RRG仍为`blocked_data`：需权威中信成员known_at/修订、版本化ETF行业映射、完整价格/可交易/分红窗口和历史准确PCF，不能把当前结构当收益或交易准入。

## 2026-09-10 12:27 对账预算、Connect 补录与 RRG 全窗口审计

- `840e7d2b`给分区闭包增加绝对截止时间，只有实际检查过的父分区才推进持久游标；到期时剩余父分区保持待处理，逐请求后的精确父闭包也复用同一截止时间。部署前一个`dc_member`标识符拆分任务的pipeline耗时114.154秒；部署后两次仍需原子扫描完整标识符集合并各生成1044个子任务，耗时102.781/108.592秒、上游调用0。该特殊`identifier_fanout`仍可能超过90秒，不能称为严格硬截止；当时待拆父任务已降为0。随后普通自动任务`a4d49e6f…`完成360次请求，pipeline 63.203秒、任务总90.356秒、失败阶段为空。生产配置保持batch360/90秒、账户和灰度500rpm、规划/发布各900秒，未提高批量。
- 两个有历史真实成功响应证据的只读接口已补入完整registry/planner/store/固定版查询和镜像路径：`moneyflow_hsgt`七字段、`ggt_daily`五字段；新`legacy_connect`默认API列表为空，没有自动启用生产采集。`ggt_daily`仅允许显式选择后的空参观测，已见1000行且`has_more=true`，不得据此声称历史完整或猜日期分片。冻结命名范围236中runtime可读由227增至229；剩余7项为`ggt_top10`、`ggt_monthly`两个公共合同缺口，`p_list`/`p_get`两个账户私有读取，`p_save`/`p_delete`两个写操作及SDK包装`pro_bar`。
- 文档锁百万行基准和四项恢复回归确认当前10秒`busy_timeout`能吸收短读写冲突；此前两次生产锁错与验收脚本的长只读事务重叠，之后五批无审计读任务成功。未改journal mode、未加第二层重试、未把finish失败降级为成功；WAL会新增checkpoint、backup及回退合同，现有证据不足。后续审计优先读SQLite backup，必须读live库时保持短autocommit。
- RRG新增固定版四年全窗口审计，`data-03885aef…`的969个SSE交易日和48个月度执行点中，1718只生命周期相交ETF形成1027679个代码日；1022792个有有效日线且同日正复权，缺4887个代码日/232只/1888个连续范围，没有前填。月度执行包络51055/51278有效、缺223；`fund_div`仅10行/4代码且缺逐代码空响应终态回执，`etf_limit`窗口内0，PCF仅2个代码日且执行日0。工具生成3655个未入队的诊断/终态/限价候选参数和5774个休眠PCF年度参数；中信成员known_at仍为0，研究继续`blocked_data`。
- 本轮代码、证据和文档均已提交并推送，`master`/GitHub/云端Git统一到`c07f176f81d3c22fbef573e86e328bf9624213e9`，5950文件、source digest `de2674c448501aa1ab8f6c356acf1f506c4409c49d791e0f5022c33a3fd0ad07`。只在采集自然排空后重启`tushare-worker`，服务healthy、OOM false；文档、研究、主服务及其他市场worker未重启。三条候选各自在Python3.10通过895项全量/68项文档/6项RRG专项及Ruff；最终完整主工作树Python3.10联合回归903项全部通过、skipped5。容器另一次因未挂载`.git`/`deploy`及子进程启动环境出现9项环境错误，不作为最终测试结论。
- 不可覆盖生产收据`/data/tushare/validation/reconciliation-deadline-20260910T0426Z/acceptance.json`，SHA256 `fecc73dcf2c397adcf07db93be35bb7b357721adc423d2752a8e232736ddca20`。云端随后发布`data-f6e77079739b69113c1ac23f1661b763e324a3b0987fa205023d4028c6a73333`；标准Mac镜像手动增量下载3907个文件后原子追平，共校验544366个文件，退出状态`verified`，本地旧版在完成前保持不变。云端目录约80G、Mac镜像约67G、云盘可用约153GiB。完整历史、修订/PIT、附件终态、RRG权威行业映射及可交易性仍是开放项。

## 2026-09-10 13:30 旧 Connect 灰度上线、RRG 补数入队与文档吞吐观测

- 旧互联互通接口先用固定版种子执行4次有界真实请求：`moneyflow_hsgt`日期范围2行、`ggt_daily`单日1行和短范围5行、`ggt_top10`单日20行，全部`sample_ok`、`supplier_has_more=false`。其中`ggt_top10`实返17列已按`trade_date,ts_code,market_type`保留身份；探测本身不自动启用、不开历史完整或PIT结论。探测报告`/data/tushare/validation/legacy-connect-probe-20260910T044428Z/report.json`，SHA256 `198c728ab4ccdc189c758c1be22d2d447ef375ae0c1740408551acaee12fc380`。
- 三接口完整合同、registry、store和逐日历史规划已上线，并在正式配置启用`legacy_connect`，历史起点`20141117`；共规划12948个稳定任务身份，每接口4316个。启用收据SHA256 `16a012da76376449c53a7f85040052bc23b67141ce863920aa6ba1117b38b336`。上线后探测结果首次进入常规publisher时暴露`api_name`缺失，发布任务在联网前失败；修复保留API身份并对既有4条attempt和4条job result做精确事务修复，未改raw/observation、未重抓上游，修复收据SHA256 `a6c622c0075a3bc72c8d915b6473039abec9d65c6c832e438ba66712e9922a42`。
- RRG四年窗口补数已从诊断计划生成8个可审核分片并导入正式队列：1718个`fund_div`及49个`etf_limit`，共1767任务；导入逐分片验证authority、pipeline锁、schema6、来源固定版、文件SHA、任务身份和整批集合，一分片一事务，0上游调用、0切换CURRENT。批次清单SHA256 `3ceaa518a73af92df4c824a9fa2c4fc7a65343a75569396643b749b091927d81`，审计与8份收据位于`/data/tushare/validation/rrg-acquisition-import-20260910T0618Z`。13:24只读快照已有1个`fund_div`进入`empty`终态，其余1717+49继续排队；这是补数管道开始消费的证据，不解除RRG的成员known_at、映射、价格缺口和可交易性限制。
- 文档worker只增加4个观测字段，不改变并发或调度。两批真实任务分别处理70/100个阶段、耗时91.780/81.817秒；下载波次19/29，波次墙钟39.287/34.293秒，双槽容量78.574/68.400秒，槽位空闲31.235/18.225秒。由此可见当前批次仍有下载槽位空闲，但一个合法的动态补位候选基准慢11.908%，未合入生产；不为追求表面并发调高worker或超时。
- 下一批8个公开目录接口已完整登记73字段但保持默认关闭：`film_record`、`teleplay_record`、`bo_monthly`、`bo_weekly`、`bo_daily`、`bo_cinema`、`fund_sales_ratio`、`fund_sales_vol`。冻结目录现为249个命名能力、238个运行时可读、11个未注册义务；其中剩余公共合同缺口为`ggt_monthly`、`rt_min`、`rt_etf_min`、`rt_etf_min_daily`、`tmt_twincome`、`tmt_twincomedetail`，另有2私有、2写操作和1个SDK包装。未实测的8项不计入生产可用数据。
- 第一批正常联网任务完成360次请求，采集任务86.354秒；后续旧Connect三接口继续推进。13:39生产验收快照为`ggt_daily` done8/empty2、`ggt_top10` done7/empty2、`moneyflow_hsgt` done7/empty2，各余4308 pending；最近1000次attempt均HTTP200、错误0、HTTP429为0。脱敏生产验收`/data/tushare/validation/legacy-connect-probe-20260910T044428Z/acceptance.json`状态`production_verified_with_gaps`，SHA256 `e081500233c7b34a38e7ed8d5200739b5f0332fb486c558b4a57192461a6b80e`，验收自身禁网且0上游调用。
- 到期发布有两次任务在206530431字节清单序列化附近触发160秒Celery软上限；精确发布intent恢复后，CURRENT和`publish_success_at`最终一致指向`data-ce5a5f6e39ec31c50145671115b76b891db4e0bad36ff978f56f65141121a3fb`。云端固定reader已对三接口读取5行并验证探测引用闭合。标准Mac镜像新增3303文件、共554935文件后原子追平同版；Mac禁网、禁凭据reader三接口均成功，报告云/本地SHA同为`4426de7c04d33904e02c2636d051c60510571ba97c5fc114a284efd181319ed8`。这完成了新归一化Connect行的离线闭包；发布尾延迟仍是开放性能问题。
- 发布后两次planning-only任务又在全量标识符发现阶段达到160秒软上限，第三次155.375秒完成；随后正常联网任务89.952秒成功。失败没有推进不完整规划游标，调度自动恢复，最近1000次attempt仍为1000个HTTP200、0个429和0个存储错误。追加运行收据`post-acceptance-runtime.json` SHA256 `2cdc9e5a80c3aba35bc37cd6fd22573a867336f64f6a0a67be34bda8d8e021cd`；完整发现扫描与大清单序列化均保留为接续性能项。
- 本轮运行代码提交到`5cd67a1a0197853d1c353981eec61c9e2227119c`，进度与接续记录随后提交master；最终Python3.10完整Tushare回归922项通过、skipped5。两个专属worker均healthy，云端Tushare目录约81G、磁盘剩余约152GiB。完整历史、旧月度Connect、实时独立权限、8个新目录接口实测、百万附件及RRG成员PIT/ETF映射继续推进。

## 2026-09-10 14:16 RRG 批次优先级与目录外八接口实测

- `e48656df`新增精确批次优先工具：执行前验证8个分片、整批哈希链、authority、共享锁和schema6；默认只生成计划。生产事务把仍为pending的1716个`fund_div`和49个`etf_limit`从原优先级调到24，两个已经`empty`的`fund_div`及所有任务身份、family、尝试、结果和门控保持不变，0上游调用。收据`/data/tushare/validation/rrg-acquisition-import-20260910T0618Z/priority-24.json`，SHA256 `72e237be7721eb76e7b3c81f38b920d5f8f0dea659252c28fd781d17f69a9cf3`。14:14只读状态仍为1716+49 pending；优先级只改变同API内部顺序，family/API公平轮转仍决定何时选中，不能把入队当完成。
- 目录外八接口的有界探针已合入`master`：静态上限11次/120秒，实际只执行8个基础请求，16秒结束；dry-run为0 authority/0凭据/0网络。执行前只暂停`tushare_acquire`消费者并让155.740秒在途规划任务自然完成，文档、研究和US任务继续；执行后四个worker的消费者全部恢复。
- `film_record`、`teleplay_record`、`bo_monthly`、`bo_weekly`、`bo_daily`、`bo_cinema`、`fund_sales_ratio`、`fund_sales_vol`均返回`api_error`，保留原始响应共同SHA `f8f00c12283dbb2123ccee6f5afb59063d2fed51e47acfc2a1812e933c6b164b`；供应商码40101表示接口名被拒绝。没有结果行，因此未生成3个依赖实际返回值的筛选请求。它不同于权限拒绝，也不能证明历史从未存在；八个完整合同继续登记但默认关闭，不自动规划历史任务。
- 不可覆盖报告`/data/tushare/validation/offcatalog-probe-20260910/probe.json`，SHA256 `745925821b4f928cb9baac0c7ae4ee2c34fc16ae2066ded4c02a019941d7c7a2`；提交的脱敏摘要为`docs/tushare-offcatalog-probe-20260910.evidence.json`。报告明确`configuration_changed=false`、`automatic_activation_permitted=false`，不含Token、订单或付款信息。
- 同批性能审计没有上线未经证实的优化：204.4MB清单分段原型只快0.739%，标识符Python顺序去重反而慢5.207%且峰值内存高38.44%，均撤销。生产仍保留现有投影和900秒规划/发布分批；14:14云端Tushare目录约83G、磁盘可用151G、100G停采线不变，两个专属worker均healthy。完整历史、修订/PIT、附件终态和RRG权威成员/映射/价格缺口继续开放。
- 剩余6个公共只读合同经复核后，`rt_min`、`rt_etf_min`、`rt_etf_min_daily`、`tmt_twincome`、`tmt_twincomedetail`已接入coverage ledger、registry、planner、Pipeline/store、固定版reader和Mac镜像安装器，但因独立实时权限、当前会话/PIT、单位、饱和及产品全集仍未验证而默认关闭。TMT只允许1..65产品、最多30个月和月窗口，并显式请求`consop_income`。`ggt_monthly`官方197正文失效且真实请求为40101，继续作为唯一公共只读合同阻塞项，禁止用`ggt_daily`自行聚合冒充。冻结范围现为249项、运行时可读243项、非运行时6项；合并后Python3.10全量939项通过、skipped5，Ruff/JSON/diff检查通过。
- 探针后首个自动发布仍在约204MB清单编码处触发160秒软上限，CURRENT未切半成品；排空采集后由同一生产`tick()`入口在Celery外完成0请求`publish_only`，生成`data-4eda061875363dca00d51bd58ca4ca54c0ae23628410b5e055e79a9e1aa2c339`。Mac客户端更新时发现安装清单漏复制既有`legacy_connect`合同，旧LaunchAgent和镜像未被失败覆盖；`56585dfc`补齐模块及回归后，安装副本隔离导入通过。Mac随后原子追平同版，新增928、完整校验559787文件；禁网络复核共同raw SHA及8个observation的SHA/API/对象引用全部一致。云端quantmind与采集worker均按相关范围重启healthy，临时加到其他worker的采集consumer已清除，专属worker恢复其声明队列。
- 部署后生产链连续完成141.571秒planning-only、139.690秒publish-only及两批真实360请求采集。两次请求窗口60.526/63.664秒，折算356.87/339.28次/分钟；任务总时长82.373/86.615秒，`failed_stage`均为空。最近1000次attempt全部HTTP200、`rate_limited=0`，其中504 sample_ok、436 empty、36 api_error、22 possibly_truncated、2 schema_gap；这些状态保留供应商真实语义，不把HTTP成功当数据完整。500rpm是账户灰度上限，接口冷却和响应耗时仍决定有效吞吐。
- 云端随后自动发布`data-d92680d004c2633d88288d9a53d965178ca811b3371b68965d4753c3a9ef90fd`，Mac第二次原子增量下载2139并校验561927文件后追平，镜像约70G。14:49精确读取8个RRG分片内全部1767个任务身份：`fund_div`为4 empty/1714 pending，`etf_limit`为6 split_pending/43 pending；1765个仍为优先级24，两个此前终态保留25。云端权威目录83G、可用160741429248字节，100GiB停线未触发。机器验收摘要`docs/tushare-next-batch-production-20260910.evidence.json`不含Token、订单或付款信息。

## 2026-09-10 15:47 实时/TMT实测、RRG精确批次与PDF回退上线

- 文档解析在严格模式触发`PdfReadError`后，会在原15秒受限子进程内用`strict=False`再读一次；第二次仍失败时继续保留`parse_failed`及两段错误。四个真实失败样本均恢复为有效`no_text`，页数为3/7/3/4；生产部署后对保留样本直接调用正式解析入口，得到`no_text`、3页、`lenient_fallback`，原始文件SHA未变。该样本在部署前已经达到`parse_tries=5`，本次没有改库或强行重排历史耗尽记录；后续新记录及正常重试会使用回退。文档专项71项通过，worker排空后单独重启并持续成功处理正常批次。
- 其余五个公共只读接口用固定种子完成5次、约7.4秒的真实有界探测，未重试：`rt_min`成功返回`SZ000001`一行及8个源字段；`rt_etf_min`和`rt_etf_min_daily`均返回40203权限拒绝；`tmt_twincome`和`tmt_twincomedetail`均返回40101接口名无效。原始响应、observation和SHA引用已进入固定版；配置未改且未自动启用。`rt_min`只有当前单点快照，尚无历史回放、时点、交易时段和单位完整性证据，仍不能直接用于研究或交易准入。
- 精确RRG批次运行器先验证8个分片、整批任务集合、配置和工具哈希、云端authority、schema6、共享锁及100GiB磁盘阈值，再只选固定清单中仍为pending的任务。生产计划核对1767个任务后，实际在69.23秒内完成360次上游调用：`etf_limit`35次、`fund_div`325次。`etf_limit`从pending35/split_pending14推进到done1/split_pending48；`fund_div`从empty6/pending1712推进到done21/empty310/pending1387。任务身份和优先级保持，运行器不发布也不切换CURRENT。不可覆盖收据`/data/tushare/validation/rrg-exact-batch-20260910/receipt-f80427372d3dc2b9.json`，文件SHA256 `bd4a0e3bb4c4f6711b560b63a178db4e6375b50ee5006639cd33d889c4e6cca2`。
- 到期后用同一生产`tick()`入口先完成0请求规划，再完成0请求固定发布；最终固定版为`data-6c9f0b0b777f5edfbb3654809006b01ea22770dd23fce20839be1a9be0d20ab1`，清单574380文件、243项scope/合同、193个已有非空发布数据集。标准Mac镜像随后原子追平同一CURRENT，镜像约72G；本地在禁网络条件下用前缀代码`SZ000001`读取`rt_min`一行成功，证明该新数据可离线消费且不会访问Tushare Pro。
- 合并后Python3.10完整Tushare回归951项通过、skipped5；本轮新改文件的Ruff检查通过，`backend/shared/tushare_pipeline.py`全文件仍有4个此前已存在的UP038建议。专属采集与文档worker均healthy，普通采集任务重启后成功完成；采集队列仍只由专属worker消费。云盘可用158941462528字节，仍高于107374182400字节停采线。
- 机器验收摘要`docs/tushare-realtime-rrg-production-20260910.evidence.json`，SHA256 `0e332138791537481ad05c472d156ac194c7f434aa623711b6270a0e4dd93d45`，不含Token、订单或付款信息。固定版发布时仍有约310.9万结构化pending；稍后实时库文档仍有约107.9万pending。RRG的成员known_at、版本化ETF行业映射、价格/可交易/分红/PCF窗口，以及大清单发布的160秒尾延迟继续开放，因此本轮完成的是接入、有限实测、精确补数、发布和本地离线闭包，不代表Tushare历史全量或RRG研究准入完成。

## 2026-09-10 17:12 发布与文档互斥、任务预算及 RRG 第二批生产验收

- 生产日志确认发布`document_index`长写事务与文档结果提交争用同一SQLite写锁：约100分钟窗口中36批成功、4次`database is locked`，发布本身又已接近160秒采集任务软限。`46e930a8`/`b4cf6a2e`让到期发布在浏览文档库前非阻塞取得既有`documents.lock`并持有至原子CURRENT切换完成；文档任务正活跃时显式返回`publish_deferred_documents_active`，不改CURRENT/检查点且不重复派发。非发布轮在规划/采集前调用一次文档派发钩子，保留两个专用worker并行。
- 首个互斥真实任务`04441eff…`在文档锁忙时13.676秒快速延期。随后固定清单已增长到约200MB，旧Celery 160/180秒软硬限与实测155–189秒发布不兼容；`40f0acc3`仅把专用采集任务外层改为300/330秒，内部上游请求数、90秒采集窗口、900秒发布/规划周期和100GiB停采线未改。部署时进一步发现未重启的Celery Beat仍在消息头写160/180；排空后只重启Beat和采集worker，清除1条过期Tushare续跑消息。
- 新Beat产生的自动发布任务`4f6896c5-354d-4a1c-ae33-359ce437cb0e`运行188.692秒后成功，0上游请求，原子切换到`data-d889a510fffc39f0c5cbeba77be0896801213f77744f67b2e2c50e7d7d116491`；发布结束后64毫秒只接收1个文档任务。重载后验收窗口的`database is locked=0`、`160s soft timeout=0`，Beat/采集/文档三服务healthy。不可覆盖收据`/data/tushare/validation/publish-document-coordination-20260910/acceptance.json`，SHA256 `db2ec1b27f676951a77a1cc3aa3773f833a41c837724fa87d8ace75636f2b6e2`。
- 标准Mac客户端增量下载1335个文件并校验581342个文件后，原子追平同一`data-d889a5…`。本地研究可继续固定release离线读取，新镜像不向Tushare Pro重拉存量，也不回写云端权威库。
- `892cd8fd`修正RRG审计的`FUND:<source_ts_code>`命名空间和固定manifest空回执计算。针对`data-d42bf11…`离线重算为：`etf_limit`观察152139对、RRG生命周期内107293对、月度执行点1648对；`fund_div`有21个代码有事件、311个有空回执，而不是旧报告的0覆盖。成员`known_at`、版本化ETF-行业映射、4887个缺价生命周期的权威可交易分类和PCF时点仍使RRG保持`blocked_data`。
- 第二个精确RRG批次验证8分片/1767任务整批哈希、authority/schema6/配置/工具哈希和100GiB阈值后，在51.961秒内完成360次`fund_div`请求：由21 done/312 empty/1385 pending推进到44 done/649 empty/1025 pending。任务身份和优先级不变，不发布、不切换CURRENT；不可覆盖收据`/data/tushare/validation/rrg-exact-batch-20260910/receipt-26d70867b68155d1.json`，SHA256 `c995c383f985ba415fb25c6255e09fdd52917f2834bffbe2028b8f8c61572f6a`。
- 目录边界复核仍为249个命名能力、243个运行时可读、6个非运行时义务，没有已注册却无reader的公开数据。`ggt_monthly`继续等待有效官方合同；`p_list/p_get`需账户所有者绑定的独立私有namespace/manifest/mirror/reader；`p_save/p_delete`永久排除自动化；`pro_bar`是SDK派生层，底层数据集已接入。这些不阻塔243项公开数据的历史闭包继续运行。
- 合并后Python3.10完整Tushare回归959项通过、skipped5，日志SHA256 `6c18f121fe2452623c439ce060dcbac72b0bdb4943bb85e5332209507855f253`；相邻33项、Ruff和diff check通过。本轮未把Token、订单、付款或上游响应正文写入Git或报告。
- 在同一共享锁空窗继续执行3个精确批次，共1024次`fund_div`请求、130.740秒；与上一批合计1384次/182.701秒，把1718个父任务最终推进到150 done/1568 empty/0 pending。四份本轮收据SHA依次为`c995c383…`、`e13a08dd…`、`55418b62…`、`4d6c730a…`，均只读保存；所有批次复用分层频控和日额度，不切换CURRENT。
- 到期自动任务`8410029c-82c9-4619-9f92-cc1483bc9e43`在193.257秒内将上述终态发布为`data-20726c7b5acbe5d15183906bba8e224d58535965f08efb0363fc296fedb51e00`。Mac新增6147个文件并校验587490个文件后原子追平。禁网固定版审计报告SHA `3e8d713d41999897d43843263960363fe281b737a3278953b9ab5c5399802df4`：`fund_div`事件926行/150代码、空回执1568代码、终态1718/1718、缺失0；`etf_limit`观察167139代码日、目标117269代码日、月度执行1648，PCF月度仍为0。闭包收据`/data/tushare/validation/rrg-fund-div-closure-20260910/acceptance.json`，SHA `4489963b84f036bb312c181caf5c61e69dc71a01c61cd08bda8df08361f83b05`。RRG继续`blocked_data`，不得据此生成交易授权。

## 2026-09-10 18:56 RRG 涨跌停与缺价诊断闭包

- `8b8e9563`新增当前后代树精确执行器和独立`fund_daily`诊断批次。前者从49个原始`etf_limit`任务中的48个拆分父任务派生哈希固定子树；计划模式禁凭据/禁网络/只读，执行模式要求authority/config/helper/task-set四项SHA、共享锁、schema6、100GiB停采线和不超过360请求/90秒。后者只允许固定清单中的`fund_daily/rrg`任务，不混入已完成的分红或涨跌停父任务。合并后11项组合专项测试、Ruff和diff check通过。
- 生产以8轮计划和有界执行把`etf_limit`子树扩展到1462个后代并消耗到0 pending；成功收据明确记录1155次请求，另1轮严格命中90秒硬限，限时前事务化进展由下一轮权威计划重新确认，不伪造该轮请求数。最终后代为726 done、53 empty、556 resolved、127 split_pending；25个根仍因空叶节点保守保留`child_not_verified`，所以请求穷尽不等于全部谱系正向证明。闭包收据SHA `2aadb6bf0f3ada39ffe8bdee273aa1a91f6ab3688acaf48a7ace216224844488`。
- 首次发布`data-0525b602612caf98e4e7e06e1dcaf3af7a28567e289cae8c6b7f77801fba3038`后，Mac新增8662个文件并校验600305个文件。离线审计显示`etf_limit`已由167139个观察代码日提升到1476541个；生命周期覆盖1027605/1027679，月度执行点51277/51278。审计器原100万行显式上限按设计拒绝截断，本轮只将上限提高到500万并保留触顶失败检查。
- 随后将1888个`fund_daily`缺价诊断范围分8个独立事务导入，在7个精确批次内完成1888次请求、238.211秒；全部返回0行，仍保持未分类，未补价、未改写历史价格或擅自认定停牌。发布`data-d54865a93b3468b2e6f4c03a6d60dbf85289e8219d87797a3478178d17cc16ab`后，Mac新增7315个文件并校验607621个文件，镜像约76G。诊断闭包收据SHA `d14dfbab6ec3bb59972e4dafaa545262d4a34b6badeef9defb53b1e4afc67eec`。
- 最终禁网固定版审计报告SHA `67fbc4e5f54063682be3439c8b0a5b7a95ec1672ee23f1a3521ae66ed07d6575`：`fund_daily`有效1022792、生命周期缺4887，`fund_adj`只在生命周期缺117且所有已有价格均有因子，月度有效价格和复权51055/51278；`fund_div`终态1718/1718；`etf_limit`生命周期1027605/1027679、月度51277/51278；PCF月度仍为0。RRG继续`blocked_data`，剩余是权威可交易分类、成员`known_at`、版本化ETF行业映射/历史全集和PCF时点/修订/权重，不是继续盲目重拉同一缺价范围。
- 三个服务均healthy，云端可用154451423232字节，仍高于100GiB停采线。文档已解析19029、待处理1086550，锁冲突修复后持续成功，但登记速度仍高于消化速度；保持现配置，先扩盘/告警并完成20批跨2个发布周期的稳态观测，再按门槛决定吞吐灰度。机器摘要见`docs/tushare-rrg-data-closure-20260910.evidence.json`，不含Token、付款、上游正文或任务参数。

## 2026-09-10 19:29 财务三表首批、容量告警与 RRG 日历证据

- 广域采集在一次标识符展开后恢复真实联网，一批完成321次请求；当时另有3个待恢复标识符父任务（`dc_member` 2、`cashflow_vip` 1），每个只做一次本地发现和子任务落盘，不重复其已保存的上游响应。它们会短时形成0请求批次，处理完后继续正常采集。19:34发布后的常规批次又在70.276秒内完成360次真实请求，身份检查0.209秒；新饱和响应产生2个后续fanout义务，继续由同一循环消化。
- 固定发布清单已增长到222754477字节。旧的非到期检查每轮完整解析全部路径，实测约31.8–36.2秒；生产同体积清单的1MiB分块SHA256基准为0.398秒，部署后真实`publication_check`为0.245秒。`d54db09f`保持指针、路径、防符号链接、内容SHA和崩溃恢复校验，只在非到期判断中省去重复JSON解析和逐路径正则；完整reader和真正发布仍执行原有清单解析。
- 文档稳态窗口34/34批成功，跨5次发布，锁错误、任务失败和软硬超时均为0；仅2/34批在80秒内命中100阶段上限，不提高并发或批量。候选在既有`document-worker-status.json`加入100GiB reserve、headroom、至少30分钟容量趋势、40GiB低余量和预计72小时触线告警。窗口末可用154367193088字节，距停采线46993010688字节；登记仍快于解析，扩盘按告警推进。
- `income_vip`、`balancesheet_vip`、`cashflow_vip`共同的120只股票、20260630、report type 1首批在48.807秒内完成360次上游调用；三项各120次，最终308个done、52个empty、0个该批pending。执行前固定任务、配置、工具和清单SHA，执行器不发布、不切换CURRENT；回执SHA256为`2768ade4231d33915ebe5d0498fc79b070d7a2599dec10c24356599842ec1e1c`。随后计划任务用184.582秒发布`data-4c12ba6d74691859358234f6aa34c7202eb3b2c90f3b04aa89eb64bac763bfe3`，发布前身份检查仅0.222秒。Mac增量下载3984个文件并完整校验614824个文件后原子追平该版，镜像约77G；存量离线读取不访问Tushare Pro。
- 在下一生产空窗继续执行三组互不重叠的同报告期三表任务。第二组首个90秒窗口完成255次，续跑48.136秒完成其余105项并重试1项；第三、四组分别在61.499/48.051秒完成360次。四组合计固定1440个任务、1441次调用、1260 done、180 empty、0批内pending，总执行窗口296.565秒。所有窗口均保持配置和CURRENT不变，回执位于同一validation目录且不相互覆盖；随后自动任务用208.297秒发布`data-14b0eaaeaae841ab728eaca5a3c6fbc79b63991cb5517716049e050b48c2e634`，身份检查0.226秒。Mac新增6749个文件并完整校验621574个文件后原子追平同版。
- RRG只读谱系复核证明25个`child_not_verified`根下的53个empty叶全部落在SSE非开市日，在固定RRG日期包络内可作日历排除，不改生产任务状态或宣称源历史完整。仍有74个开市日生命周期`etf_limit`缺口，唯一月度执行缺口为`20260401 / SH560890`；成员known_at、版本化ETF行业映射、权威可交易分类和PCF月度证据仍缺，状态保持`blocked_data`。

## 2026-09-10 20:06 容量告警与扩盘执行路径

- 生产 `document-worker-status.json` 在42分钟有效窗口内把磁盘状态升为 `warning`：可用152439779328字节，距100GiB停采线45065596928字节，观测消耗约1.93GB/小时，约23.314小时后触线。这个短窗包含多次大清单发布和定向财务批次，不外推为稳态增长；但已满72小时扩容预警门槛，结构化拉取和文档处理继续，100GiB硬停线不变。
- 数据盘是500GB整盘ext4 `/dev/vdb`，无分区和LVM；当前宿主有`resize2fs`，但没有云厂商CLI。因此可审查执行路径是：云控制面/API将块设备扩到至少1TiB，宿主确认`lsblk`已变大后在线`resize2fs /dev/vdb`，再复核挂载、SQLite、worker、发布和Mac单向镜像。云厂商侧操作涉及实际计费，当前无可调用的主机凭据/CLI，记为外部执行项，不因此缩减接口、历史、字段或原文。
- 目录口径的apparent bytes分别为：attachments 12924368679、documents 22826561577、objects 13338397464、parquet 5827564714、archives 25421565077、releases 25782175211、validation 3937878382。其中固定版、归档和活动数据可能共享硬链接，不直接求和当物理占用；生产Tushare树与Mac镜像约77GiB作为当前量级。

## 2026-09-10 20:44 基金净值、指数权重与公告追加生产验收

- 指数权重、基金净值两个默认plan-only的精确批次已合入并部署。云端Python3.10生产镜像、完整仓库、2CPU下982项Tushare回归通过；同镜像0.75CPU有1个大响应测试超过自身10秒预算，提升2CPU后通过，记为资源假阴性而非功能放行。Mac合并相关27项通过，Ruff check通过。
- `fund_nav`有效批次在49.349秒内完成360次请求，得到165 done/53 empty/142 split_pending；`index_weight`在46.728秒内完成360次，得到139 done/204 empty/17 split_pending。两批合720次，共享500rpm账户闸门、接口限速、100GiB停采线和不发布契约；无配置或CURRENT竞态。
- `history:equity_announcements`一轮正常规划新增500，随后两轮断网、锁内有界规划再新增500/281，最终offset1323/done1。三接口合计1332任务：8 done/54 empty/1270 pending，已恢复常驻消费。两批数据已由192.183秒发布进入`data-3eee75afb22ae4bea72b9ac5826e6bea6b7d98f0f2e600adfd1b04f11677c2e1`；Mac新增1994文件、完整校验626068文件并原子追平。
- 三个专属服务healthy、GitHub/Mac/云端源码均为`a4a5595d`。生产可用空闲151496171520字节，最新80分钟趋势估计26.938小时后触及100GiB线，仍是`reserve_within_72h_at_observed_trend`警告。扩至至少1TiB的云厂商侧操作待外部控制面/API执行；采集不缩范围，并由100GiB硬保护自动停领。RRG的成员known_at、版本化ETF行业映射、权威可交易分类和PCF时点仍未闭合，继续`blocked_data`。

## 2026-09-10 21:42 基金份额历史规划、第五批财务三表与容量缓解

- `8a9e5dfb`新增独立 `history:fund_share_history`，不重置未完成的 `history:market`。断网候选固定19900101—20260902日×沪深共26788个任务及集合SHA；部署后首helper提交500项再因报告字段读取错误退出，v2从offset500幂等继续53轮，最终offset26788/done1、26788 pending。两helper均保留，上游/凭据/发布/CURRENT均为0；常驻worker恢复后已开始消费。
- 第五个三表精确批次固定20260630、report type 1的120个共同股票，三API各120。62.104秒完成360次真实调用，各API均116 done/4 empty，批内0 pending；配置和CURRENT未变、未发布。manifest SHA `6012834024373909222a59b83cdc4440f64b997021f7e633d7991cfa55ef9460`，收据 SHA `8f088af0b5ab123a8e41e04ddfe1d7fde66513e7b675c91b8f6597eeb4018881`。
- 容量复核确认当前全量manifest为230623171字节；同一旧版在release和archive路径共享inode（link count 2），每次发布的物理新增约一份manifest，不能按两条路径重复计算。按近20—22分钟一版约占短窗1.8GB/小时增长的35%—40%，仍是可压缩的显著来源；文档另有约109.5万pending。生产发布间隔已从900秒原子改为3600秒，账户500rpm、360请求/90秒、规划、镜像和100GiB硬停线均未改；配置SHA由 `4ac7b381…` 变为 `da45afae…`。当前文档批次自然结束后已暂停文档worker，保留全部队列/原文；结构化采集和Beat恢复healthy。扩盘完成并复核后再恢复文档消费。
- 候选在Mac相邻44项通过；云端生产镜像、断网、只读源码、4CPU下985项完整Tushare回归180.631秒通过。2CPU全套仅一项既有时间预算测试偶发少完成2个请求，单项与新追加3项重跑均通过。RRG只读复核确认PCF历史队列已在推进，但现有Tushare接口仍不能补出成员known_at、历史ETF行业映射、权威可交易分类或PCF公布时间/修订/权重分母；继续保持blocked_data并停止重复拉相同缺价范围。

## 2026-09-10 22:00 基金份额追加游标生产修复

- 首版追加 planner 的策略签名同时包含 `history_start` 和 `market_apis`。v2 helper 显式传入 `['fund_share']`，生产配置依赖相同的默认值；两种表示生成不同签名，恢复常驻 worker 后游标曾重置到offset12495/done0。任务ID是幂等主键，已规划任务、终态与原始响应没有删除、覆盖或重复。
- `4302970a`把该固定family的签名缩为真正改变任务集合的`history_start`，并增加“显式/默认父API列表不得重置已完成范围”的回归测试。修复后Mac相关45项和Ruff通过，云端生产镜像断网4项通过。v3在共享锁内确认任务集合仍为26788项、SHA不变、offset26788/done1；收据SHA `604cf8835dad7ff8df7fc8b174e8cb742370a10826bcbfafdca40ed668b71ed0`。
- Beat恢复后立即触发一次正常生产采集，133.442秒成功结束；周期后游标仍为offset26788/done1，任务为5 done、26783 pending、0 error，证明一次性helper与常驻配置不再互相重置。Tushare worker和Beat保持healthy，文档worker继续停用等待扩盘；固定版发布仍按3600秒周期执行。

## 2026-09-10 23:00 第六批财务三表、固定版全覆盖审计与经济日历饱和接线

- 第六个财务三表精确批次固定20260630、report type 1的120个共同股票，三API各120，在49.490秒内完成360次上游调用；`income_vip`、`balancesheet_vip`、`cashflow_vip`各115 done/5 empty，批内0 pending。批次本身不发布、不切换CURRENT；收据`/data/tushare/validation/financial-pit-batch-20260910/acceptance-batch-6.json`，SHA256 `77c30b102c78833aa90cbcc62fe5d698d75f47362803bf68bee195d2fd8d1289`。
- 后续一小时周期由正常生产入口在246.873秒发布`data-66f5a3d5084ac67a14240f56ebc0e4b9eb54fbdf3911cec06bfc7ca2f8da3ffb`。标准Mac镜像新增11645个文件、完整校验646423个文件后原子追平，LaunchAgent退出0；Mac继续从固定版离线读取，不向Tushare Pro重拉存量。
- 同一固定版在云端与Mac分别执行覆盖审计，报告字节一致，SHA256 `c6d31d8736d43f8771e7a4076aa5a0769319c196a704b0748435f6abe63e3f89`：243个已登记运行时API全部进入规划，0个登记未规划；193个已有发布数据集，另外50个只有blocked/permission/empty等证据。该结论证明规划接线覆盖，不证明每项历史、修订、附件或PIT完整。
- `66df93ba`上线`eco_cal`饱和后的来源观察值拆分。两个各100行的旧封顶父任务均从已保存object/observation原地恢复，父请求重发0次、原始引用和尝试保持；每个父任务连接24个后代并保留`coverage_proven=0 / universe_unverified`。Tushare原始`country`字段同时含国家名与分类标识，均按来源原样处理，不凭名称删值。
- 阶段快照后继续由`calendar_extra`常规队列自然消费，48个唯一后代最终为24 done/24 empty，全部48次请求HTTP200、每个后代只尝试一次；空结果保留`empty_unverified`。最终闭包收据`/data/tushare/validation/eco-cal-saturation-20260910/closure-20260910T150820Z.json`，SHA256 `31499010eb699b440b69f48831c383197c092da710138db7e68d4d110bf3ade4`。
- 完整回归989项、生产镜像断网专项29项及Ruff通过。结构化worker和Beat保持运行，文档worker继续按容量缓解方案停用；发布周期3600秒、账户灰度500rpm、单接口既有限速、100GiB硬停线均未改。扩盘仍是外部云控制面动作，不缩减已登记数据范围。 23:12复核worker/Beat均healthy、OOM false、restart0，部署后16个任务成功、HTTP429/错误/任务失败均为0；云盘可用148709466112字节，距100GiB停线41335283712字节（38.496GiB）。`fund_share`独立历史游标仍为offset26788/done1。

## 2026-09-10 23:36 第七批财务三表与第二批基金净值

- 23:16一次只读审计与生产SQLite写事务重叠，任务 `f08cc911…` 在响应检查点提交时触发一次 `database is locked`。审计连接全部关闭后，自动重试任务 `d4549374…` 在155.511秒内成功；未重启服务、没有遗留读连接。由于失败发生在响应提交边界，该次网络响应可能被后续任务重新请求，本轮不宣称这一故障窗口上游调用严格去重。后续审计只使用离线backup或短自动提交查询。
- 下一小时自动任务 `50d567d4…` 在258.323秒内完成0请求固定发布，原子切换到 `data-1ed56821ebf8f42ca999dc754829b80fa0ee27cbae3a0501ec399001ee62e10f`。固定清单对比确认 `eco_cal` 新增的48个终态后代已进入该版：24 `done`、24 `empty`；两个来源父任务仍保留 `split_pending / universe_unverified`，不外推来源国家全集。
- 发布后排空并暂停专用Tushare worker和Beat。第七批财务三表清单与两次审计重算一致，360项均为首次尝试；85.137秒内三接口各完成120次，分别118 `done`、2 `empty`，批内0 `pending`。清单SHA `421403ebe023809072473eedf44015376e6c24d9f240afe3f34407e838d7ee9d`，收据SHA `a3b5dd26a914c1d1ceae78d7ac4aac623e4d871fdbf1ce33385f519e46fa6bf0`。
- 同一独占窗口按只读价值审计执行第二批 `fund_nav`：固定290个拆分叶和70个历史根、共215只基金，全部 `pending/tries=0` 且与首批无重叠。48.565秒完成360次请求，结果133 `done`、93 `empty`、134 `split_pending`；后者继续由标准日期二分处理。清单SHA `2e82be986b08365bef13a698824c17d977eccdda3e16f32aa75149e5dcd19eed`，收据SHA `e4277d3b3537dd65a31982ba03db072bf0bae5a9488bbfd431f4cb48c8b70b35`。
- 两个精确批次均通过manifest、任务集合、生产配置、prepare/runner哈希、authority、schema6、共享锁和100GiB余量校验；合计720次请求，不发布、不切换CURRENT。结束后worker和Beat恢复healthy；先后成功完成一次153.294秒规划和一次62.446秒采集，继续收到后续正常任务，未出现新锁错或HTTP429。文档worker继续按容量缓解方案停用。23:41云盘可用147862343680字节，距100GiB停线40488161280字节（37.708GiB）。这两个批次等待2026-09-11 00:26:31到期的下一次固定版周期统一发布。
- 标准Mac LaunchAgent按900秒周期自动启动镜像，没有手工触发；23:41:08新增下载10090个文件、完整校验656514个文件后退出0并原子追平 `data-1ed568…`，本地manifest SHA一致、错误日志0字节。该版包含本轮发布前的 `eco_cal` 及既有终态；刚执行的财务第七批和 `fund_nav` 第二批仍需下一次固定版发布后才会进入Mac。

## 2026-09-10 23:53 第八批财务三表与第三批基金净值

- 常规采集任务 `fca03d57…` 自然运行145.086秒并成功后暂停Beat，再停稳专用worker。第八批财务三表重新固定 `002215.SZ` 至 `002335.SZ` 的120个共同股票，三API各120；47.626秒完成360次请求，各API均116 `done`、4 `empty`，批内0 `pending`。manifest SHA `2b485d6b92ea4ad198a8d466640dd00676a52365929eedbbf15859e91dfc54c5`，receipt SHA `702572f42c48783721c57834770178d0c0c9a60096f4e84f98708dc1648f5a81`。
- 同一独占窗口的第三批 `fund_nav` 重新固定270个当前拆分叶和90个历史根、共225只基金；49.602秒完成360次请求，得到202 `done`、39 `empty`、119 `split_pending`。manifest SHA `add2f3cf9c145628fea2e861d908d8940cc1914a32f51244645ec187bb7d91c7`，receipt SHA `6826ccd3616cdbaa4c900770dd22fd8e7f48629db36ea2dc5861e2655426ebf9`。
- 两个批次均先通过默认plan-only，再以重新冻结的任务集合、配置、prepare/runner哈希逐项核对authority任务，使用共享锁、500rpm账户闸门、360请求/90秒边界和100GiB停线；总计720次请求、97.228秒，不发布、不切换CURRENT。结束后worker/Beat恢复healthy并收到下一正常任务，文档worker继续停用。批次后云盘可用147769589760字节，距100GiB线40395407360字节（37.622GiB）；这两批与上一波720项一起等待2026-09-11 00:26:31到期发布。

## 2026-09-11 00:25 fund_share 精确批次

- `a7982586`复用现有 exact runner 增加 `fund_share` 固定清单和执行入口；`54a517c4`根据首批诊断将新清单从最早pending改为最近pending优先，旧清单仍可验证。历史任务、普通planner游标和数据均未删除或改写。相关10项测试、Ruff、格式及语法检查通过；改动前生产镜像断网全套994项通过、174.688秒。
- 第一批固定1990-01-01至1990-06-29的沪深各180项，46.368秒完成360次真实请求，全部empty。它只证明这些精确请求当次为空，不证明相邻日期或供应商历史下界。manifest SHA `b1b70f174b342a8e72587ec61445d9b3821620b57e252c0eb9803e61012f85db`，receipt SHA `47f764871e17a5a5c18cf890bb569777e8b4b9008d5f109fd1b4dd44d63abb99`。
- 第二批从26,397个pending中固定当前最新360项，日期2026-02-19至2026-08-18、沪深各180。51.099秒完成360次调用，256 done/104 empty、批内0 pending。manifest SHA `e2606ccd5a9671ba42211025939056512af8465b0d2e75cce701283a1f84c8ba`，receipt SHA `80d8490b2412615153849b6edcd9561491481a4c0d4fe813ec3888982d2dc0bc`。
- 两批均默认plan-only并固定任务、配置、准备器和共享执行器哈希；真实执行通过authority/schema6/ENABLED/共享锁/360请求90秒/100GiB余量门控，不发布、不切换CURRENT。worker和Beat已恢复healthy，云盘可用147501383680字节；结果等待正常固定版发布和Mac自动镜像。
- 到期后的正常publish-only任务 `0b768175…` 用220.122秒原子切换到 `data-d5d918ce4bc2cfd3ef6e58c5caeefa29c7d9f9715cd5b8cd0d03d4d07cab64de`。Mac标准镜像新增下载14028个文件、完整校验670543个文件后退出0并追平，错误日志0字节；无Token且禁止网络/DNS的固定版读取返回5行 `fund_share` 样本并标记0上游调用。最终worker/Beat healthy、restart0、OOM false，部署后HTTP429、供应商频率错误和任务失败均为0；云盘可用146955538432字节，距100GiB线39581435632字节（36.863GiB）。

## 2026-09-11 01:02 三组精确批次与全接口固定版覆盖

- 对固定版 `data-d5d918ce4bc2cfd3ef6e58c5caeefa29c7d9f9715cd5b8cd0d03d4d07cab64de` 断网审计：243个运行时API全部已规划，193个已有发布数据集，50个只有显式empty/blocked/permission证据；249项冻结命名范围中243项运行时可读，唯一公共只读合同缺口为 `ggt_monthly`，其余5项是2个私有读、2个写操作和1个SDK包装。机器证据为 `docs/tushare-fixed-coverage-20260911.evidence.json`；这证明接线范围，不证明每项历史、修订、附件或PIT完整。
- 常规任务排空后停Beat与专用worker，从权威库重新冻结三个互不重叠批次，1,080项均为 `pending/attempts=0`。财务三表第9批48.788秒完成360次，344 `done`/16 `empty`；`fund_nav`第4批49.170秒完成360次，179 `done`/41 `empty`/140 `split_pending`；`fund_share`第3批46.786秒完成360次，270 `done`/90 `empty`。三批固定manifest、任务集、配置、prepare/runner哈希，不发布、不切换CURRENT。
- 批次完成后Tushare worker和Beat恢复healthy，文档worker继续按容量方案停用。云盘可用146862358528字节，距100GiB硬线39488176448字节（36.776GiB）。新增结果尚未进入固定版，等待正常一小时发布周期和Mac自动镜像；发布后再做断网reader及全清单哈希验收。
- 固定版 `fund_nav` 当前可查询488037个最新自然键、529只基金，仅占22216只 `fund_basic` 代码的2.381%；36.26%的最新行来自仍开放的截断父区间。`fund_share` 当前可查询222116条最新观察、2210只基金、149个日期，仍有26037个pending。两者继续保持 `history_complete=false`、`historical_versions_complete=false`、PIT未就绪。

## 2026-09-11 01:21 基金净值与份额继续补采

- 正常固定版尚未到17:31Z发布点，因此没有把等待当作阻塞。暂停Beat后，前一常规任务 `f0594d64…` 已自然成功；随后另一个已接收任务 `e366f80d…` 在停止worker时被Celery标为revoked，重启后明确丢弃。它不属于精确清单；逐请求写入仍采用既有幂等终态，未完成逻辑请求由后续正常任务继续。该停机边界不用于宣称常规批次调用严格去重。
- 停服权威库重新冻结 `fund_nav` 第5批：282个拆分叶、78个历史根、209只基金，46.609秒内360次请求得到212 done/43 empty/105 split_pending。`fund_share` 第4批固定2025-02-23至2025-08-21沪深各180项，46.919秒内得到279 done/81 empty。两批共720项均为pending/tries=0、通过plan-only和全部哈希固定，不发布或切换CURRENT。
- 两批后worker和Beat恢复，`e366f80d…` 的撤销状态被消费，下一正常任务 `9ccb3909…` 已接收。固定版仍为 `data-d5d918…`，本轮及上一轮合计1,800个新增精确终态等待正常发布；Mac固定版继续保持可离线读取的上一版。
- 财务精确准备器已改为沪、深、京轮询和跨epoch logical-key排重，避免第10批继续集中深市或重复已在其他epoch完成的同一请求。旧manifest兼容测试、均衡/排重测试及三类exact runner共14项通过，Ruff和格式检查通过；已有runner测试仍报告一个未关闭SQLite连接的既有 `ResourceWarning`，不影响本次结果，后续单独修复。
- `index_weight` 固定版断网审计得到252470条latest、156个指数和258个指数日期快照，但88.1%的行仍来自截断父区间。下一360项离线候选中326项为新月窗、34项为低边际拆分后代；批准继续一批以扩大月度覆盖，不把日期二分解释为单日行数上限的闭包方案。
- `index_weight` prepare已实现“每个指数完整自然月优先、拆分后代回退”，继续保留指数轮次及SH/CSI交错；旧生产manifest兼容验证通过。相关7项单测、四类exact批次联合21项、Ruff和格式检查通过。

## 2026-09-11 01:49 固定版追平与下一批冻结准备

- 正常publish-only任务在253.219秒内完成，0上游请求，原子发布固定版 `data-469f77386a446840774a5d78b7384d0bedcc4c6b1f89035b3512b52fe09703c1`。Mac标准镜像新增下载9447个文件、完整校验679991个文件后追平同版；固定版断网读取实际返回153122条目标日期范围内的 `fund_share`、654968条latest `fund_nav`，以及三个深市样例的70条 `income_vip`，过程0上游调用。
- 为冻结下一批精确任务，Beat已停止；先取消专用worker的 `tushare_acquire` 消费，再等待当前任务自然成功并确认active为0，随后停止worker。这个顺序避免新增撤销任务，后续精确批次结束后恢复worker和Beat。
- 财务第10批首次准备安全失败，未生成manifest也未调用上游。20260910 epoch中三表共同pending候选有1172组，SH/SZ/BJ分别400/400/372，均为20260630/report type 1；跨epoch排重后当前候选窗口内为0，因为3600个logical key已在其他epoch终态。准备器将每市场的有界候选读取深度由目标量的10倍扩大为100倍，以到达更早报告期；仍保持只读、有限查询、三表共同叶、跨epoch排重和360项硬上限。若更深扫描仍不足，则记录为非阻塞数据状态并继续执行 `index_weight` 第2批。

## 2026-09-11 02:00 财务与指数权重精确批次完成

- 扩大候选扫描后，20260910 epoch仍全部属于跨epoch终态重复；准备器改从仍有5873组三表共同pending叶的20260909 epoch冻结第10批。固定20260630/report type 1的120只股票，沪、深、京各40只，三API各120；360项全部pending且attempt为0。45.880秒完成360次调用，各API均113 done/7 empty，批内0 pending。manifest SHA `249dc0c4080b1431c166fa7d24d26d67f20a713ec72d5d95457c961f1606c55a`，任务集SHA `a708b170bf1b0f579212685cd5b15e46a34f2a3ba83001f493024472377f9edb`，receipt SHA `669359b8ab0c970632daa2a49c7ab9e8a6b1b9c54cbe0ba3056be578bf156c28`。
- `index_weight` 第2批固定203个指数的360个完整自然月窗口，时间范围20171101—20260831，SH后缀246项、CSI后缀114项；无拆分后代或部分月回退，全部pending且attempt为0。44.706秒完成360次调用，316 done/9 empty/35 split_pending。manifest SHA `132c2479dd229531a0931d462a403d9368aee036e7a356f1a333afa03f1c5f28`，任务集SHA `850db14860259a8634600e5edb104af4f7ea06a1c85d5161653f8b725ada15ac`，receipt SHA `38f8fb58f9292242521e74426a04da349e1ce95108b920eef91bcec641181ae7`。
- 两批共720次请求、90.586秒，均通过不可变manifest、任务集、配置、runner哈希、schema6、authority、共享锁、90秒和100GiB门控；不发布、不切换CURRENT。结束后专用worker和Beat恢复healthy、restart0、OOM false，重新订阅 `tushare_acquire` 并开始正常任务。云盘可用145720508416字节，距100GiB线38346326016字节；Tushare权威目录约103747731456字节。
- `fund_nav` 空结果复核第一阶段prepare已实现：显式固定release，只读选择满24小时的一次有效空观察及同基金单日正向控制，固定原始observation/object和控制observation/parquet哈希，不追随CURRENT、不读取凭据、不调用上游、不改任务状态。显式d5固定版临时schema6夹具离线重建得到77个目标；生产runner、A/B执行、7天第二轮和收据仍未实现，未在生产执行。

## 2026-09-11 02:07 基金净值与份额下一波补采

- 固定版发布下一到期点尚有约36分钟，自动任务明确返回 `publication=deferred/pending=true`，因此等待期间继续补数。Beat停止并取消专用worker的 `tushare_acquire` consumer 后，已接收任务 `4d0c4d61…` 继续运行到165.176秒成功、active变0；随后才停止worker。本窗口没有撤销任务、没有重启在途请求。
- `fund_nav` 第6批固定254只基金的360项首次请求，包括210个pending拆分叶和150个pending历史根。46.823秒完成360次调用，217 done/31 empty/112 split_pending。manifest SHA `e657e14e57c55e0610f3fbfc209d24fc07398e55c77aada06a8cd20e0dfa3e69`，任务集SHA `0abc7131c789c054becbdada6a238244063e722f924934e1a21e2d9dd4dcb76e`，receipt SHA `9ec3b31129be3e732a37a0b813bfb622ab4e9432ce06a740d265d645fea6d057`。
- `fund_share` 第5批固定20240826—20250221的沪深各180项首次请求。45.523秒完成360次调用，248 done/112 empty。manifest SHA `ac7a797301125bba23ad4d99510643c39c0ff6fdb92fd46bc6f96fcad8798a9b`，任务集SHA `0db2e907d4a3ca84bc539d5cc33d47be30f9a1e4a2ee5c8d074b4380fd717d9f`，receipt SHA `cfb85916a177819a4a43ee09668fa107a1e4d45a9519edd9882aa1a2ae61ef8d`。
- 两批共720次请求、92.346秒，均通过plan-only和任务/配置/prepare/runner哈希门控，不发布、不切换CURRENT。结束后专用worker和Beat恢复；新增结果与前一波720项共同等待正常固定版发布和Mac自动镜像。
- `fund_nav` 第一轮空结果成对复核runner已合入：默认仅离线验证不可信manifest；执行固定authority/release/config/任务集/组合代码哈希，以非阻塞共享 `pipeline.lock` 强制writer排他，并按A原请求+B单日正向控制成对追加不可变观察、attempt和receipt。有效空、合法非空恢复、冲突、两次失败重冻结后manual_hold及收据崩溃恢复均有测试；宿主停Beat/worker仍是明确操作前提，runner如实记录但不在无Docker socket的容器内伪装验证。Mac和云端生产镜像联合10项通过，commit `f3b9489d`。第二轮7天门控、`review_exhausted`、发布和生产复核仍未执行。

## 2026-09-11 02:21 基金净值空复核到期审计

- 当前固定版 `data-469f7738…` 与停写authority按真实时间生成第一轮清单，得到0个到期目标，0凭据读取、0上游请求、0任务状态变化。未来时间只读审计暴露单个无正向控制基金会使整批失败；`84b5ca7f`改为逐基金跳过缺控制项并继续，其余证据损坏仍整批拒绝。Mac与云端prepare+runner联合11项通过。
- 修复后的未来到期审计得到181个结构候选，其中155个有固定版正向控制、26个缺控制而保持未选；最早 `not_before=2026-09-11T12:26:34.077603Z`，最晚 `2026-09-11T16:58:11.073563Z`。这只是显式未来时间的只读调度审计，不是可执行生产manifest或复核结果；届时须重新停写、使用当时固定release和authority生成新清单，最多155组/310次A-B请求。
- 审计结束后专用worker和Beat恢复；正常固定版仍等待一小时发布周期。缺控制的26项记为非阻塞数据缺口，不影响其余155项后续复核，也不授予任何历史完整或PIT结论。

## 2026-09-11 02:56 精确波次固定版与二轮复核部署

- 正常任务 `104fd67c…` 在284.594秒内完成 `publish_only`，0上游请求，原子切换到 `data-dbd1efcca51b442c2a72cbacc28dd4d61883c0a232eebecc410d48bdf02d7ec9`。新manifest有692727个文件；done81569、empty76175、split_pending2854、pending3705514。
- 财务三表第10批、`index_weight` 第2批、`fund_nav` 第6批和 `fund_share` 第5批共1440个唯一task均已在该固定版闭包。逐任务核对当前observation/object/parquet引用并重算实体SHA，empty/split_pending任务同时出现在manifest gaps；闭包报告SHA256为 `4251f6cdae60858a1ed5cf9545da170637476e96f5bd5f17c0720b0e52941a63`。这些任务返回财务三表594行、指数权重132936行、基金净值246610行、基金份额124615行，空和拆分状态仍如实保留。
- Mac标准LaunchAgent新增12735个文件、完整校验692727个文件后以exit 0原子追平同一release。Mac客户端屏蔽socket/DNS并清除token，云端容器使用 `--network none` 和空token，两端都对新版完成离线读取：`income_vip`4行、`fund_nav`301行、`index_weight`2000行、`fund_share`1138行，全部 `upstream_calls=0`。
- `fund_nav` round 2已支持7天门控，固定round 1旧release、attempt、manifest和A/B四证据哈希；round 2可以使用当时的新release。`review_exhausted` 不改原empty任务或父拆分gap，非空恢复继续走标准normalize/reconcile。候选22项、Mac18项和云端生产镜像18项相关测试通过；生产尚未到round 1时间门，因此0复核调用。
- `54ae40bd` 已合入并推送master，Mac/GitHub/云端Git统一；云端worker与Beat在在途任务自然成功后重建为healthy，restart0、OOM false。重启后首任务 `1783a093…` 用145.746秒成功。固定证据为 `docs/tushare-exact-wave-release-20260911.evidence.json`。
- 非阻塞项：通用CLI的 `codes` 默认映射到 `ts_code`，但 `index_weight` 存储列是 `index_code`，因此按指数代码筛选会拒绝；按日期固定版读取已通过。这是reader选择器缺口，不影响本批原始数据闭包，后续单独修正。全局 `history_complete`、历史修订完整性和PIT仍为false，RRG仍为 `blocked_data`。

## 2026-09-11 03:22 下一精确波次与指数代码 reader 上线

- 停Beat、取消专用worker采集consumer并等待在途任务自然结束后，四个固定清单顺序完成1440次请求：财务三表第11批49.138秒，335 done/25 empty；`index_weight`第3批47.332秒，316 done/9 empty/35 split_pending；`fund_share`第6批46.794秒，248 done/112 empty；`fund_nav`第7批45.100秒，204 done/35 empty/121 split_pending。合计188.364秒，折算458.686 rpm；每批均固定任务集、配置和工具哈希，不发布或切换CURRENT。合并权威摘要SHA256为`2565ba8492ebdb0db0dda3b56f219a48b480bb91e8cbd745f38c253bf2418db4`。
- 生产配置继续使用`tiered_v1`、账户硬上限与灰度档500 rpm。300/400/500三阶段验收收据仍在authority；500阶段已有100/100 HTTP 200、0供应商限频和495.868 rpm突发中位数证据。当前精确波次的持续吞吐接近但未超过账户门，API合同、显式冷却和`cyq_perf`日配额继续取更严限制。
- 后续自动生产任务`dec4e5f7…`实际完成360请求，360个HTTP 200、0个HTTP 429、0个供应商频率错误；采集阶段56.737秒、任务总58.050秒，分别折算380.704/372.093 rpm，失败阶段为空。`pipeline-status.json`同时持久显示2000积分还有85天、`expires_within_90_days`提醒、预计到期后8100分，以及`cyq_perf`当日200000硬上限账本ready。
- `77c1a3fa`修复通用CLI按registry键选择代码列：`index_weight`默认使用`index_code`，并允许显式已有`source_*`列接受供应商后缀代码。生产镜像17项相关测试通过。云端禁网/空Token与Mac禁socket/DNS/无Token分别查询`SH000003`和`000003.SH`，每种40行；两端7行导出SHA均为`529084f1146c422c2355f3263f91993b4bfa676ee0a3d7b6997ffb84791b6b14`，上游调用0。
- 提交已推送并部署。云端GitHub fetch超时作为非阻塞网络项记录，改用同一Git提交的bundle快进，云端与Mac均为`77c1a3fa`且目标文件SHA一致。仅重启`quantmind` API加载reader，HTTP健康检查200；采集worker、Beat、DB和Redis保持healthy。Mac定时客户端副本已重装并核对脚本/存储层SHA。
- 到期publisher在303.982秒软超时前已原子切换`CURRENT`到`data-f9c557872d2b7793779791dded640acce597cf5ceb07e35dacf81d9d5af74ee9`；指针和274924292字节manifest的SHA一致。下一任务用173.057秒完成`verified_current_intent`恢复，0上游请求、失败阶段为空，并推进`last_success_at`和下一发布点。新固定版有705154文件、88415数据分区、93724缺口；这再次暴露发布尾延迟，但没有半成品版本或重复上游抓取。
- 任务级闭包逐一核对1440个task：1103 done、181 empty、156 split_pending；关闭SQLite读取后，对4139个唯一observation/raw object/Parquet引用重算物理SHA与字节，empty/split_pending同时存在于manifest gaps。返回行数为财务三表665、`index_weight`132350、`fund_nav`244214、`fund_share`122450；不可覆盖闭包报告SHA为`073eb220fe6a2ad3599b946610fd296139eae36a5d812743719148d9599ada21`。
- Mac第140次标准LaunchAgent新增下载12426文件、完整校验705154文件，退出码0且错误日志0，原子追平同一固定版。云端`--network none`和Mac禁socket/DNS、无Token复核结果一致：`income_vip`4行、`index_weight`内部/来源码各1369行、`fund_share`1015行、`fund_nav`523行，全部0上游调用。
- 最终云端authority约98.581GiB、Mac固定镜像约84.952GiB，云盘可用143650902016字节（133.785GiB），高于100GiB停采线。机器证据为`docs/tushare-exact-wave-reader-20260911.evidence.json`。全局历史、修订/PIT和RRG成员/ETF映射缺口仍开放，RRG继续`blocked_data`。

## 2026-09-11 04:20 第二次精确波次补采

- 在固定版 `data-f9c557872d2b7793779791dded640acce597cf5ceb07e35dacf81d9d5af74ee9` 的停写窗口内，重新冻结并串行执行四个360请求精确批次。财务三表第12批45.634秒，357 done/3 empty，返回733行；`index_weight`第4批45.310秒，316 done/9 empty/35 split_pending，返回132005行；`fund_share`第7批44.310秒，239 done/121 empty，返回106834行；`fund_nav`第8批44.587秒，208 done/39 empty/113 split_pending，返回241163行。合计1440次上游请求、179.841秒、480735行。
- 四份manifest和receipt按批次号以0444归档到authority `validation/`，每份receipt的内容摘要均与runner输出的`receipt_id`一致。合并验收重算1440个唯一task及1440个object、1440个observation、1268个Parquet的物理SHA，0缺失、0哈希错误；权威摘要SHA256为`e88c8f8638bcc22d1f8d5495c7bea98c7ebef89895efce94ea1db9f53ae4203a`。
- `CURRENT.json`窗口前后SHA256均为`96fad1dd7c619a8e0b8f45cf4c4706afcfda1220c598ef35f130887e054d872f`，未发布、未切换固定版。窗口后云盘可用143531327488字节，高于100GiB停采线。
- 恢复`tushare-worker`时Compose同时重建postgres容器，数据卷保留；DB、API、专用worker和Beat均恢复healthy，restart0、OOM false。停写窗口前保留在Redis的两个普通采集消息因自带`expires=110`已过期，worker恢复后按Celery语义标记`REVOKED(expired)`，未形成部分任务。04:19:57 Beat按120秒周期投递新任务`aee5532f…`并由专用worker接收，后续幂等继续。
- 机器证据为`docs/tushare-exact-wave-20260911T0406.evidence.json`。当前固定版尚未包含本次新增结果，等下一次正常publish-only后再做Mac单向镜像和双端断网读取验收。全局仍为`history_complete=false`、`pit_verified=false`，RRG继续`blocked_data`。

## 2026-09-11 04:31 index_weight 公共 reader 一致化

- `6c9e79e7`将代码字段默认解析下沉到`tushare_store`：只要查询携带`codes`且调用方没有显式指定`code_field`，store就按数据合同键选择`ts_code`或`index_code`。CLI、FastAPI、QuantBot和直接`read_dataset`现在共用同一逻辑，schema同时返回`default_code_field`。
- 生产Python 3.10镜像中store/CLI/API/Agent联合21项通过；Mac宿主Python 3.13因未安装`duckdb`无法运行数据测试，不是代码回归。云端对固定版`data-f9c557…`屏蔽socket/DNS并置空Token，FastAPI与QuantBot都在未指定`code_field`时查到5行`SH000300`指数权重，首行一致，`upstream_calls=0`。
- 代码已推送GitHub并在云端快进到同一提交；只重启`quantmind` API、健康检查HTTP 200。`tushare-worker`、Beat和DB未因这次代码发布重启，采集任务继续成功接续。
- 保留数据缺口：旧固定版`index_weight.con_code`仍为`000001.SZ`这类供应商格式，没有`source_con_code`，不应与内部`SH/SZ/BJ`前缀代码直接联接。研究适配层暂时需显式转换；后续固定版再保留来源字段并发布内部规范列。证据为`docs/tushare-reader-default-20260911.evidence.json`。

## 2026-09-11 05:02 第二次精确波次发布与指数成分代码兼容

- 正常发布首次在采集后进入约275MB清单序列化时触发300秒软上限；两个恢复子进程随后碰到`tushare-worker`的1GiB cgroup上限并被内核OOM终止。Beat停止、精确consumer取消后，最后一个已在途的恢复任务在288.135秒内完成原子发布，`CURRENT`切到`data-7be20672a3a9d0fbaecd571b0ce6da741da23e1257fe55f02d114b06e8865a09`。这不是上游、磁盘或数据损坏；发布intent和不可变目录使重试没有重复抓取或暴露半成品。
- 新固定版逐项包含04:06波次的1440个唯一任务：1120 done、172 empty、148 split_pending；重算1440个object、1440个observation和1268个Parquet实体SHA均通过，manifest gap匹配320项，验证错误0。闭包报告SHA256为`55ca1d341ea1c6a44ec3ee26ed67f132a410c1ba9092f60045301d99225137dc`，机器证据为`docs/tushare-exact-wave-fixed-release-20260911.evidence.json`。
- `cb7fffa7`使未来`index_weight`写入同时保存内部前缀`con_code`和供应商原值`source_con_code`，store在查询旧版或混合分区时做兼容投影并按规范自然键去重，不回写不可变Parquet。生产固定版禁socket/DNS、空Token读取中，FastAPI与QuantBot均自动按`index_code=SH000300`返回5行；首行`con_code=SH600000`、`source_con_code=600000.SH`，上游调用0。机器证据`docs/tushare-index-constituent-normalization-20260911.evidence.json` SHA256为`cec13affe749d76b350c44f1e499c67b1f7653653304c14916d701f0db1cb125`。
- `f71e407a`只把云端专用`tushare-worker`内存额度从1GiB增至2GiB。排空后重建的worker实际限制2147483648字节、healthy、restart0、OOM false，并加载上述代码；Beat单独重建为healthy。DB、主API、文档及其他市场worker未因容量修复重建。
- Mac标准LaunchAgent第144轮新增下载11459个文件并完整校验716614个文件，exit 0、错误日志0字节，原子追平同一固定版；本地manifest实算SHA与release ID一致。Mac生产镜像容器在`--network none`、空Token和只读镜像挂载下得到与云端相同的5行指数成分结果，上游调用0。单向镜像证据`docs/tushare-fixed-release-mirror-20260911.evidence.json` SHA256为`eb96be4d3efa23a4d628e01788e0e84a2f094a946d238b6c16d8e72653813b0f`。

## 2026-09-11 05:08 核心行情第一批真实补采

- `056ad757`新增复用既有exact helper的核心行情冻结/执行入口；首次生产prepare因真实job还含字段和质量合同元数据而安全失败，0上游调用、未生成manifest。`5a196944`修正为允许这些已纳入task identity的标准元数据，同时继续严格限制六个API和唯一`trade_date`参数。生产镜像9项核心及helper回归通过。
- 停写authority以新固定版和全部`trade_cal`实体SHA冻结60个共同SSE开市日，范围20250829—20251226；`daily`、`adj_factor`、`daily_basic`、`stk_limit`、`suspend_d`、`moneyflow`各60项，共360项，全部pending/tries0。manifest SHA为`cf7ee55cfd0288af9ac91f69f6f6c5f487c0547d169f94effea72249512402a9`；plan-only确认authority、凭据、网络、写入和发布均未访问。
- 真实执行受90秒硬窗约束，90.103秒完成340次请求，339 done、20项尚未开始、1项blocked，返回1529654行；按API为`adj_factor`310797、`daily`304489、`daily_basic`304489、`moneyflow`293838、`stk_limit`315191、`suspend_d`850。持续等效吞吐226.408次/分钟，低于500rpm账户门，主因是大结果本地转换与落盘；没有429或供应商限频证据，不能用请求上限冒充实际端到端吞吐。
- blocked项是`stk_limit@20251009`：HTTP 200且5516行raw object/observation已保存，硬截止在normalize阶段触发`TimeoutError`，未生成Parquet；其余20项保持pending/tries0，由常规队列继续。闭包重算340个object、340个observation和339个Parquet实体SHA，`CURRENT`保持上述固定版；receipt SHA256为`5cb56861e295be7818598f6bc57e205ffd8b9a54856447dc52955f18190ca15f`，闭包SHA256为`ecba9e2f29da9b5b3e43ba4504697673e990d3eda9485bf49563588e658cbdca`，机器证据为`docs/tushare-core-market-batch-20260911.evidence.json`。
- 全局`history_complete=false`、修订/PIT未验证，RRG仍为`blocked_data`。云盘可用约142.39GB，高于100GiB停采线；本批只扩充权威存量，后续固定发布和Mac自动镜像仍按单向协议完成。

## 2026-09-11 05:44 基金行情、已购政策与分红历史精确批次

- `907ad7b5`新增三套默认plan-only的精确批次入口。Mac与生产镜像各23项组合测试通过；已购政策准备器把47个跨epoch重复任务折叠为277个不同逻辑请求，保留源任务统计但不浪费上游预算。代码已推送master并通过双节点内容摘要和Git快进检查部署到云端。
- 基金行情批次固定20190410—20191231的180个共同SSE开市日，`fund_daily`、`fund_adj`各180项。44.713秒完成360次请求，全部done，返回259149行，等效483.081次/分钟。第一次执行在上游调用前被操作员遗留的只读审计进程占锁拒绝，0次调用、CURRENT未变；同一进程还使05:35常规任务`f9861892…`在initialize提交时锁失败。关闭进程、重新冻结相同清单后精确批次成功，05:43常规恢复任务`60a25fb1…`随后用176.329秒成功完成。
- 已购政策批次完成277次请求：`monetary_policy` 7项均empty；`npr` 189 done、78 empty、3 split_pending，返回3711行，38.062秒。清单锁定单接口限速为央行货币政策执行报告200rpm、政策法规500rpm，账户总闸门500rpm。
- 分红历史批次按沪深北各120只股票固定360项，44.455秒完成360次请求，355 done、5 empty，返回17200行，等效485.885次/分钟。三个批次合计997次HTTP 200、0次429、280060行；逐文件验证997个object、997个observation和907个Parquet哈希，错误0。
- 三批均固定release、任务集、配置、准备器和执行器SHA，使用authority/schema6/ENABLED/排他锁/100GiB余量门，且不发布、不切换CURRENT。权威闭包SHA分别为`0161dc75c71940750bafbb35fe10493480beeb9db1071aa452df062d81e4adab`、`c9b1a46c8db8918d36a1c6feb6d1176fb66d603927dd0b4d811afd926ecbb42a`、`8608a6b5c5b220efe33b9522c6c01a264dba4918bf040e74324dd9ad9f2fab87`；仓库机器证据为`docs/tushare-exact-history-batches-20260911.evidence.json`。
- Tushare worker与Beat已恢复healthy；worker实际内存2147483648字节、restart0、OOM false。新增活动数据等待正常一小时固定发布和Mac LaunchAgent单向镜像，因此当前固定版仍为`data-7be20672…`。完整历史、修订/PIT和RRG准入仍未闭合，继续`blocked_data`。

## 2026-09-11 06:25 发布时限、固定版闭包与公告首批

- `1647f792`把专用 Celery 发布任务的软/硬上限从300/330秒扩大到600/630秒，采集本身仍由每轮请求数和秒数独立约束。Mac与生产镜像各26项针对性测试通过，容器运行时反射值为600/630。首个到期任务`a5dbe244…`在138.544秒内完成`publish_only`并原子发布`data-051d825b3220a2419e8291fcf15d7917eee9547ccb90c67ed8344b925f36c813`，没有再触发300秒软超时。
- 新固定版manifest为282216992字节，SHA与release ID一致，含725606个文件条目和92254个数据集。只对不可变manifest做流式扫描，并用短索引查询映射任务：核心行情、基金行情、已购政策/央行和分红四批共1337个object、1337个observation、1246个Parquet全部进入固定版，逐实体重算SHA错误0；固定版闭包SHA为`552d4a076fb5173e2e5cf0530ebe4ab66c1995c4711192bb0d5c73d84ccbc834`。
- Mac第148次标准LaunchAgent新增下载8991个文件、完整校验725606个文件，exit 0且错误日志0字节，原子追平同一release；本地282216992字节manifest实算SHA一致。在生产镜像`--network none`、两个Token变量为空、镜像只读挂载条件下，`fund_daily@20190410`返回5行、`upstream_calls=0`，证明当前存量可脱离Tushare Pro读取。
- `9c383c8d`新增默认plan-only的公告`anns_d`精确批次入口；Mac和生产镜像各31项组合测试通过。停Beat、取消专用consumer并自然排空后，三份清单全部固定上述release、authority配置、任务集、准备器和runner哈希。基金行情第3批覆盖20180712—20190409的180个共同交易日，43.619秒完成360次、全部done、243626行；分红第2批沪深北各120项，44.333秒完成360次、352 done/8 empty、17501行。
- 公告第1批90.674秒完成221次调用：219项返回2000行上限并进入`split_pending`，1项empty，140项保持pending；共1313650行。220次HTTP 200，另1次`ReadTimeout`按可重试pending保存且没有写入部分payload。第一次操作员验收脚本把这类pending误当成必须0尝试，原失败闭包保留；语义修正后的不可覆盖v2闭包逐文件核验220个object、220个observation和219个Parquet，验证错误0。
- 本轮三批合计941次上游调用、940次HTTP 200、0次429、1次可重试传输超时，runner时间合计178.626秒、返回1574777行；941个调用对应的940个完整object/observation和931个Parquet物理SHA均通过。专用worker和Beat已恢复healthy，worker 2GiB、restart0、OOM false，`tushare_acquire`消费恢复并接收新任务。
- 当前authority为106420995288字节，云盘可用141094637568字节，高于107374182400字节硬停线；Mac镜像93203988480字节。本轮三批尚未进入下一小时固定版或Mac镜像，保留`history_complete=false`、历史修订/PIT未完成和`rrg_status=blocked_data`。机器证据为`docs/tushare-publication-announcement-wave2-20260911.evidence.json`。

## 2026-09-11 06:51 第三次精确波次与容器启动隔离

- 再次排空专用队列后冻结三份互不重叠的不可变清单。基金行情第4批覆盖20171018—20180711的180个共同SSE交易日，`fund_daily`、`fund_adj`各180项，44.548秒内360项全部done，返回243322行；分红第3批按SH 124、SZ 124、BJ 112固定360只股票，44.541秒内360项全部done，返回17487行。
- 公告第2批从585个未尝试叶中固定360项，90.303秒完成242次调用：239 `split_pending`、2 `done`、118项尚未开始、1项`blocked`，共1442455行。blocked项HTTP 200返回6000行，原始object/observation和两个日期二分子任务均已保存，只在90秒边界的规范化阶段超时，因此没有声称Parquet成功，也不作为上游权限、频率或数据丢失故障。
- 三批合计962次调用全部HTTP 200、0次429、1703264行；逐实体验证962个object、962个observation和961个Parquet SHA，错误0。三份权威闭包SHA分别为`d0a2cedfa212e346bddc6ac38bf0dd79b05fd4d7ae326e9ac652f658cb8b4cf8`、`39e8cc1b4276b8a1ee4856efdd00ffda46d7d43f9602a0d7da946f3662ccea7c`、`373495ee992a9fe3f89c6dcc08844e406e58fd21103d809555772ccf8d23076a`。
- 运行时检查发现所有Python进程在用户代码前导入LiteLLM，并默认尝试下载模型费用表，给断网plan-only带来无关的约10秒等待。`ffe883a6`在导入前默认设置`LITELLM_LOCAL_MODEL_COST_MAP=True`并允许显式覆盖；`1fe6ee08`让同一测试兼容仓库与容器安装路径。Mac主机、Mac容器、云端生产容器各2项通过，真实云端公告plan-only约5.01秒且不再出现远程费用表警告。
- Mac、GitHub和云端源码已对齐`1fe6ee08`，专用worker与Beat恢复healthy，restart0、OOM false。authority当前约106924476093字节，云盘可用140415729664字节，高于100GiB硬停线。`CURRENT.json`仍为`data-051d825b…`，第二、第三波次都等待正常小时发布和Mac单向镜像；`history_complete=false`、修订/PIT未验证、RRG继续`blocked_data`。机器证据为`docs/tushare-exact-history-wave3-20260911.evidence.json`。

## 2026-09-11 07:35 第二、三波固定版闭包、NPR尾批与快照容量恢复

- 每日07:00整机离线快照恢复了一个未发布的`.building`暂存树，盘内可用空间从约140GB降至94011957248字节，低于100GiB硬停线；07:07—07:11的Tushare任务因此安全返回`blocked_disk_reserve`。暂存树没有`COMPLETE`、不是`latest`，正常停止快照服务后只清理该未发布暂存，已发布整机快照、Tushare authority和Mac固定镜像均未删除；可用空间恢复到约232.9GB。为避免次日重复，整机快照timer已停用，待云盘扩容并复核快照headroom后恢复；Tushare小时发布和15分钟Mac镜像继续运行。
- 余量恢复后的正常任务用226.548秒发布`data-bdb8d5c76f676b5595a8af871cbc563e3705ff25713c4a5514c61b9aca9e6b68`。286136683字节manifest实算SHA与release ID一致，含738613个文件条目和95006个数据集。固定版闭包确认第二、三波2160个清单任务出现中有131项是公告批次有意重复冻结的未尝试项、2029个唯一任务；1902个object、1902个observation、1892个Parquet全部进入固定版并通过物理SHA，错误0。闭包SHA为`7839fb9668eef4a405afd5de439d27af1f622e83c0019a51074a1f1a37b4b81d`。
- Mac第152次标准镜像新增13006个文件并完整校验738613项，exit0、错误日志0字节，原子追平同一release；本地manifest SHA一致，镜像约94820483072字节。生产镜像在`--network none`、两个Token变量为空和只读镜像挂载下读取`fund_daily@20171018`返回5行，上游调用0。
- `a6d3a9ef`新增NPR历史叶默认plan-only精确批次。生产首次准备发现原审计6项中已有1项被常驻worker完成，0调用安全停止；`206e6c5d`改为冻结当前最多6个合格叶并把实际任务哈希写入清单，执行器仍在排他锁内跨所有epoch重查logical attempts。剩余5项用2.3秒完成5次HTTP 200、0次429、1223行，结果2 done、1 empty、2 split_pending；5个object、5个observation和4个Parquet物理SHA全通过。清单SHA为`c311855ef87ee00b6f491bb296f2b9620277c36e77e5149baeef637306476831`，闭包SHA为`4bfd840c22dc760b110e1a4a8ea7ae57c27f5d9675f3e12c5f93c81e67003f39`。
- 主API已用`docker-compose.yml + deploy/compose.cloud.yml`正确重建，监听`127.0.0.1:18000`并返回HTTP 200；Web、专用worker和Beat均healthy、restart0、OOM false。新Python进程默认`LITELLM_LOCAL_MODEL_COST_MAP=True`且不再产生无关远程费用表请求。Mac、GitHub和云端源码在证据提交前对齐`206e6c5d`；NPR尾批尚未进入下一固定版，完整历史、修订/PIT仍未完成，RRG继续`blocked_data`。机器证据为`docs/tushare-wave23-fixed-npr-storage-20260911.evidence.json`。

## 2026-09-11 07:56 第四次历史精确波次

- Beat先停止，专用worker取消`tushare_acquire`接新任务；已在途的`c3bb96f6…`用186.776秒自然成功，active/reserved均为空后才停止worker，全程没有revoke。四份清单均固定`data-bdb8d5c76f676b5595a8af871cbc563e3705ff25713c4a5514c61b9aca9e6b68`、配置、任务集、prepare和runner哈希；默认plan-only的authority、凭据、上游、写入、发布访问均为false。
- 基金行情第5批覆盖20170118—20171017的180个共同SSE交易日，43.860秒完成`fund_daily`与`fund_adj`各180次，360项全部done、240136行。分红第4批固定沪深各180只，44.779秒完成360次，全部done、22402行。
- NPR首批二分后新生成的4个未尝试叶在1.785秒完成4次调用，2 done/2 split_pending、1014行。公告第3批固定360个未尝试拆分页，但执行上限主动降为180次；63.277秒完成180次HTTP 200，4 done/176 split_pending/180项保持pending，返回1051468行，没有再次触及90秒规范化边界。
- 四批合计904次上游调用、904次HTTP 200、0次429、1315020行；逐实体重算904个object、904个observation和904个Parquet SHA全部通过。权威闭包`validation/exact-history-wave4-20260911/closure.json` SHA256为`c7863997652553170b7fc051d9a61c61f5ed09bd94d7b06d612bde5effd5d143`，清单和收据均以0444不可覆盖方式归档。
- 专用worker与Beat已恢复healthy、restart0、OOM false，主API保持healthy；authority约108096892848字节，云盘可用232403939328字节，高于100GiB硬停线。`CURRENT`仍为`data-bdb8d5c7…`，本波与两批NPR尾项等待08:17之后的正常固定发布及Mac单向镜像。
- 并行RRG只读审计确认行业价格与日历覆盖已经较高，P0缺口仍是带`known_at`、修订版本和来源证据的中信行业分类与历史成员PIT；继续增加普通价格行不能解除`blocked_data`。完整历史、历史修订和PIT仍未闭合。机器证据为`docs/tushare-exact-history-wave4-20260911.evidence.json`。

## 2026-09-11 08:10 第五次历史精确波次与全库缺口排序

- 第二个有界窗口同样先停Beat、取消专用consumer接新任务，已在途`b2bd0a1d…`用186.708秒自然成功；active/reserved为空后才停worker，未撤销任务。四份新清单固定同一`data-bdb8d5c7…`版本和全部配置/代码/任务哈希，默认plan-only所有访问标志为false。
- 基金行情第6批覆盖20160426—20170117，43.795秒完成360次、全部done、221980行；分红第5批沪深各180项，51.828秒完成360次、全部done、22381行；NPR第3批4次得到1 done/1 empty/2 split_pending、1007行；公告第4批继续以180次执行上限在66.745秒得到6 done/174 split_pending/180项未开始、1036404行。
- 合计904次HTTP 200、0次429、1281772行。904个object、904个observation与903个Parquet逐实体SHA通过，少1个Parquet对应真实empty。权威闭包`validation/exact-history-wave5-20260911/closure.json` SHA256为`f6d735723ca2204af5fbba28ebb85b1e05572ab09b321ecd1a3d9e400f7b4c6d`；worker与Beat恢复healthy、restart0、OOM false。
- 08:05只读一致快照显示history尚有2205669 pending、3570 split_pending。最大待扩展族依次包括`dc_member`346878、股东集中度173867、`fina_mainbz`134362、`index_daily`102082、`factor_value`101987、`tdx_member`101980、筹码族85465、ETF申赎篮子82051、`fund_portfolio`45725。下一阶段优先为`index_daily`和`fina_mainbz`增加同等级exact runner，再处理需PIT版本/known_at/来源证据的成员类与ETF篮子；`cyq_perf`继续受200000/日硬账本约束。
- authority约108426751071字节、云盘可用232011051008字节。当前固定版仍为`data-bdb8d5c7…`，第四、第五波与NPR链等待08:17后的正常发布和Mac镜像；完整历史、修订/PIT与RRG准入仍未闭合。机器证据为`docs/tushare-exact-history-wave5-20260911.evidence.json`。

## 2026-09-11 08:36 第四、五波固定版发布与Mac断网验收

- 正常定时任务`bab2fab7…`用215.575秒执行`publish_only`，0次上游请求，原子发布`data-512b55ad56927ba2924e95bd0904ac35df963b4243d2df5b51f2a9a04b54cbca`。289623876字节manifest实算SHA与release ID一致，包含748694个文件条目和97480个数据集条目。
- 固定版闭包确认NPR首个尾批及第四、第五波至少1813个唯一object、1813个observation和1811个Parquet全部进入发行清单并通过物理SHA，检查5437个发行路径，错误0；相关数据约644.05MB。最终权威闭包`validation/release-512b55ad-wave45-closure-20260911-v3.json` SHA256为`8174984804f4bfbfa66037a44e4f613ad735369785a8b36c1c4934c08d6a6a69`。
- 发布器按设计排除`validation/`。13个批次manifest、receipt和波次闭包在authority独立通过存在性与SHA校验；前两个不可变闭包文件分别记录清单分段标记和验证目录纳入策略的错误假设，由v3显式取代，没有删除审计轨迹。
- Mac标准LaunchAgent第156次运行下载10080个文件、完整校验748694项，exit0、stderr 0字节，原子追平同一release和manifest SHA。生产镜像在`--network none`、socket/DNS双重阻断、两个Token变量为空和只读挂载下，`fund_daily@20160426`、`dividend@SH600416`、`anns_d@20120201..20120215`及`npr`均返回5行，上游调用0；NPR 20080316—20080324窄窗真实返回0行，保持为空而未补值或重拉。
- 发布报告继续保留账户500rpm、`cyq_perf`每日200000次硬账本、10100积分及2026-12-05后预计8100积分事实，并在到期前85天产生可观察提醒；证据不含Token或订单信息。API、专用worker和Beat均healthy、restart0、OOM false；云盘可用231380914176字节，高于100GiB硬线。
- 全库任务继续推进，08:36快照为91794 done、81304 empty、3875074 pending、3997 split_pending。完整历史、历史修订和PIT仍未闭合；RRG P0仍缺带`known_at`、修订版本与来源证据的中信一级行业分类及历史成员，因此保持`blocked_data`。整机快照timer继续disabled/inactive，待扩盘和峰值headroom验证后再恢复。机器证据为`docs/tushare-fixed-release-wave45-20260911.evidence.json`。

## 2026-09-11 09:08 第六次历史波次与两个新精确runner生产验收

- 第六波在固定版`data-512b55ad…`上冻结1366个唯一任务，得到1131个持久化上游尝试、全部HTTP 200、1251369行；1131个object和observation、1129个Parquet逐实体哈希通过。NPR第4批4次、分红第6批360次、公告第5批180次完成；基金行情第7批在227次持久化后遇到SQLite锁，第8批只冻结当时仍未尝试的78个重叠任务和282个新任务，没有重放第7批的持久化请求。
- 基金行情第7批失败点可能已有1个上游响应到达但未提交checkpoint，因此权威请求数保守记为1131—1132，不宣称严格上游去重。失败闭包原样保留，最终v2闭包SHA为`c34cf0600884488cade46237a20d0a7e9672fc93798d18938ad8352227843f60`。
- 停机过程中常规任务`0b912542…`在取消consumer后竞态进入worker；30秒停止超时导致worker exit137，Celery重启后记录`REVOKED/expired`。它不属于精确批次，未完成幂等工作继续由常规调度处理；这个边界不用于证明常规请求严格去重。后续不再强停：`07c68005…`自然成功，下一任务`ea0cbd4b…`继续运行。
- `index_daily`和`fina_mainbz`精确prepare/runner/test已在master的`abb1a626`上线，本地和云端各31项测试、Ruff、格式与编译均通过。生产首批各360次、合计720次HTTP 200、0次429；`index_daily`得到354 done/6 empty和56994行，`fina_mainbz`在固定的1996—1997报告期请求窗内得到360个显式empty。
- `fina_mainbz`空响应只固定本次公司、类型和报告期请求事实，不证明供应商历史为空；公告时间、`known_at`、修订和PIT均未验证，因此暂不盲目扩展更老空窗。两个新runner的720个object、720个observation和354个Parquet物理闭包通过，closure SHA为`be4bf19d6c11f03e9e3bd0237097b6291f70a767006884437d02bfea40e1618e`。
- 新结果仍只在authority，等待09:21:15 CST后的正常原子发布和Mac单向镜像。API、专用worker与Beat均healthy、restart0、OOM false；authority约109344540319字节，云盘可用230902153216字节，高于100GiB硬线。历史、历史修订和PIT仍未完成，RRG继续`blocked_data`。机器证据为`docs/tushare-exact-history-wave6-20260911.evidence.json`和`docs/tushare-index-fina-exact-production-20260911.evidence.json`。

## 2026-09-11 09:57 VIP主营业务全计划生产批次

- `93c4abb7`把专用worker停机改为先停Beat、取消精确consumer、等待active/reserved连续两次为空后再正常停止，失败时退出75且不stop/revoke；云端宿主3项测试和真实排空通过。`00b0360f`、`865530f0`、`813fef4f`新增并上线`fina_mainbz_vip`合同、默认plan-only精确批次与1990Q1—2026Q2的146季度规划，P/D/I共438项，重复规划插入0项。
- 四批依次覆盖2024Q1—2026Q2、2016Q3—2023Q4、2001Q3—2016Q2、1990Q1—2001Q2；30、90、180、138次调用分别耗时11.481、30.350、71.924、19.451秒。合计438次全部HTTP 200、0次429，返回1520320行；最终239 blocked、60 done、139 empty，已无未尝试VIP计划项。
- 四批逐实体重算438个object、438个observation和299个非空Parquet的SHA与字节数，错误0；对应验证文件合计287123009字节。闭包SHA依次为`35c45154523d5e8f77812168fc457b2de78e3cf52a8e255ddc266a99786c7ff4`、`9945a40fc8a1a48ef22e7a0a3edf86863d60bb41d5c5a357d737c7d286c0df50`、`82951b4f3d0ac19c446c8ae311af09bf44f0ea807f6ec315ee0260dea6669a94`、`cf4674b64458ac974fb0b5e089a6d71acfae1ee88b9e4b67716f314cea6cca1b`。第三批首个闭包错误要求`empty_unverified`也有Parquet，原失败证据保留，v2语义修正后零错误。
- 239项返回`has_more`或达到操作性饱和阈值。官方VIP输入只记录`period`和`type`，没有offset/page/limit，因此没有猜测分页；原始返回全部保留，等待供应商确认合法续页方式。空响应也不证明供应商全历史不存在，`history_complete=false`、历史修订、`known_at`和PIT仍未验证，RRG保持`blocked_data`。
- 当前固定版`data-3eec661f…`已包含第六波和index/fina新runner结果；Mac LaunchAgent第161轮exit0并追平同一版本。VIP四批等待10:26:06 CST正常固定发布和随后15分钟单向镜像。API、专用worker和Beat已恢复healthy、restart0、OOM false，常规采集继续；云盘可用229843632128字节，高于100GiB硬线。机器证据为`docs/tushare-fina-mainbz-vip-production-20260911.evidence.json`。

## 2026-09-11 10:49 指数/基金波次发布与董秘问答首批

- 在安全排空窗口内执行 `index_daily` 第2批、`index_weight` 第5批和 `fund_daily+fund_adj` 第9批，共1080次请求、全部HTTP 200、零429、312891行；逐实体重算1080个object、1080个observation和1028个Parquet的SHA与字节，错误0，总计45724019字节。财务PIT按360和180两种规模准备均因共同待拉叶不足而零调用停止；旧`index_weight` plan缺`would_write`字段作为工具schema缺口保留。
- 10:30:25 CST正常发布原子切换到`data-00177d548289255711d171ddd8ffc86332f5078951ccb8a618792c82a0528288`。295830034字节manifest实算SHA与release ID一致，含768829个文件引用、101451个数据集和100894个缺口；全部引用存在且大小匹配，抽样1024个SHA零错误。本轮三批及438个`fina_mainbz_vip`任务都已进入固定版。
- `ee548878`、`32558212`新增并优化沪深董秘问答默认plan-only精确入口。它只选history未尝试叶，排除跨epoch已有尝试/终态，按SH/SZ与question/reply四层公平轮转并优先拆分页。Mac与生产容器各16项组合测试、compile和diff check通过；两端运行时均未安装Ruff，旧drain模拟测试在应用容器内有两项子进程超时，真实云端排空正常且没有revoke或强杀。
- 董秘问答首批固定上述新release与配置/代码/任务哈希，360项含320个拆分叶和40个未拆历史窗；85.95秒完成360次HTTP 200、零429、857441行，结果133 done、40 empty、187 split_pending，并生成374个子任务。360个object、360个observation和320个Parquet物理SHA全通过，共689364476字节；authority闭包SHA为`bdafe46d30482cb4b68d8a12adf66a2ce034113d8826e9ad912893903e315a9e`。
- Mac第164轮标准镜像在10:49:38 CST下载7439个缺失文件并原子追平同一固定版；双端manifest SHA/字节一致，本轮4363个引用在Mac全部通过物理校验。在`--network none`、Token为空和镜像只读条件下，`index_daily`与`fund_daily`各读取3行且`upstream_calls=0`。
- 禁网验收同时发现`fina_mainbz_vip`虽有299个Parquet进入固定版，但公共reader未注册该runtime-only合同而返回`Unknown dataset`。`38c579a9`把VIP合同加入store并复用`dataset_identity=fina_mainbz`，11项相关测试通过；云端与Mac随后均在同样禁网条件下读取3行、0上游调用。只重启主API加载reader，采集worker和Beat保持运行。
- API、专用worker和Beat均healthy、restart0、OOM false，云盘可用228590608384字节，高于100GiB硬线。董秘问答首批仍等待下一次固定发布；原始文档worker继续等扩盘/headroom验证。完整历史、修订、known_at和PIT未闭合，RRG继续`blocked_data`。机器证据为`docs/tushare-index-fund-exact-wave-20260911.evidence.json`与`docs/tushare-irm-qa-production-20260911.evidence.json`。

## 2026-09-11 11:10 指数日线、基金净值与基金份额精确波次

- 安全排空专用队列后，以固定版`data-00177d548289255711d171ddd8ffc86332f5078951ccb8a618792c82a0528288`冻结三份各360项的精确清单。三份plan-only均确认不访问authority、凭据、上游和发布，`index_daily`还显式给出`would_write=false`；旧`fund_nav`/`fund_share`通用runner缺少该展示字段，作为非阻塞schema缺口保留。
- `index_daily`第3批44.372秒完成360次，281 done/79 empty、45152行；`fund_nav`第9批48.922秒完成360次，207 done/40 empty/113 split_pending、245455行；`fund_share`第8批44.847秒完成360次，248 done/112 empty、101328行。
- 三批合计1080次HTTP 200、零429、391935行。逐实体核验1080个object、1080个observation和849个Parquet的SHA与大小，错误0；唯一物理文件共53879750字节。authority闭包`validation/exact-index-fund-wave-20260911T1100/closure.json` SHA256为`f5a026bfae854ba5f12abb5684bf22f8e4d253b9e5488ce300235b242ec04c9d`。
- worker、Beat与API恢复healthy，restart0、OOM false；排空过程未调用revoke，恢复时Redis中一个超过110秒有效期的旧排队消息被Celery按`revoked/expired`丢弃，未运行、未调用上游或写入部分结果。云盘可用228470714368字节，高于100GiB硬线。本波与董秘问答首批等待正常publish-only及Mac单向镜像；完整历史、修订、known_at和PIT仍未闭合，RRG继续`blocked_data`。机器证据为`docs/tushare-index-nav-share-wave-20260911.evidence.json`。

## 2026-09-11 11:56 董秘问答与指数/基金波次固定发布

- 11:37:45 CST正常`publish_only`原子发布`data-82ece8a2297797f1f2508f4a782d897164d910a650b45c06df87ae8c24bb1838`；301007830字节manifest实算SHA与release ID一致。四份冻结清单的1440个任务通过权威终态结果连接到1440 object、1440 observation和1169 Parquet，4049个唯一引用、743244226字节均进入发行映射，元数据、大小和物理SHA错误0。authority闭包SHA为`d0ba398fb7bdfe8dda0c7e1b57d4076b62e3157d75d77edeff76b073a91f8346`。
- 最初Python正则扫描因CPU回溯慢而只读终止，未写部分闭包；`jq --stream`在14.5秒完成同一完整清单扫描。发行manifest不嵌入pipeline task_id，闭包采用“冻结清单→终态result→内容寻址文件→release文件映射”的可复算成员关系。
- Mac LaunchAgent第168轮exit0、stderr0并追平同一release，客户端报告778375个发行引用；独立重算本轮4049个文件全部通过，镜像约93GiB。手动`kickstart -k`可能中断了一个已预填文件但尚未记日志的在途自动客户端，因此第168轮`downloaded_files=0`不用于证明无传输；以后运行中不使用`-k`。
- Mac生产镜像容器在`--network none`、socket/DNS阻断、两个Token变量为空和只读挂载下，对`index_daily`、`fund_nav`、`fund_share`、沪深董秘问答各读取3行，上游调用0。`bdd0fd98`同时补齐共享基金exact plan的`would_write=false`，Mac和云端各10项测试通过，无需重启。
- API、专用worker和Beat均healthy、restart0、OOM false；云盘可用228029927424字节，高于100GiB硬线。完整历史、修订、known_at和PIT仍未闭合，RRG继续`blocked_data`；整机快照timer和原始文档worker继续等扩盘/headroom复核。机器证据为`docs/tushare-fixed-release-82ece8a-wave.evidence.json`。

## 2026-09-11 12:20 指数权重、基金行情与董秘问答第二波

- 在固定版`data-82ece8a2297797f1f2508f4a782d897164d910a650b45c06df87ae8c24bb1838`下冻结并执行`index_weight`第6批、`fund_daily+fund_adj`第10批和沪深董秘问答第2批，共1080个任务、1080次上游调用、1123137行。基金360项全部done；指数权重316 done/9 empty/35 split_pending；董秘问答157 done/12 empty/191 split_pending。`split_pending`仍是必须继续处理的防截断义务，不能计为历史完整。
- 指数权重在第359次请求响应落盘后，因并行只读审计在DELETE journal数据库上持有共享锁而于SQLite提交失败。358个已提交请求没有重放；第359项从HTTP200、50行的孤立object、observation和Parquet按三重内容哈希恢复SQLite引用，新增上游调用0；确认未调用的第360项用单项哈希固定清单执行1次完成。失败、恢复和尾项收据均不可覆盖留档。
- 三批的1080个attempt、1080个object、1080个observation和1059个Parquet逐实体SHA通过；物理证据共718607021字节。authority闭包`validation/release-82ece8a-exact-wave2-closure-20260911.json` SHA256为`8d1acfd1bfc65b89744bdb84d7da5a25c4045fec763352afaba3565dd0acc99e`，固定版未发布或切换，等待正常publish-only和Mac单向镜像。
- 只读RRG审计确认继续扩`ci_index_member`、申万`index_member_all`、东方财富或同花顺成员不能解除中信历史成员PIT缺口。后续只沿现有bridge记录从首次抓取开始的forward-only vintage，并按`etf_basic.index_code`定向补`fund_portfolio`和`index_weight`；2022—2026历史放行仍需官方中信调整档案的`known_at`、revision/撤回和来源哈希。RRG保持`blocked_data`。
- 财务PIT冻结器已改为优先选择三表共同叶，再按API独立填满剩余预算；一个API候选不足不再阻塞另外两个API。指数权重plan同时补齐`would_write=false`。13项专项测试和编译检查在Mac通过，待master提交、云端部署和真实批次验收。

## 2026-09-11 12:30 财务PIT选择器生产闭环

- `93e5d4ac`把财务PIT冻结器改为共同叶优先、三API独立补齐，`da6b5dea`再为runner增加准备器SHA固定、`would_write=false`和执行时强制校验；两端master与源码摘要对齐，Mac和生产容器各13项专项测试通过。脚本通过bind mount直接部署，无新增依赖或镜像重建。
- 安全排空后在原先因共同叶不足而停止的`20260910` epoch重新冻结，得到`income_vip`、`balancesheet_vip`、`cashflow_vip`各2项。plan-only确认不访问authority、凭据、上游、不写入或发布，并固定manifest、任务集合、配置、runner及preparer五类SHA。
- 真实批次6次调用在1.082秒内完成，全部HTTP 200且为精确空响应；6个任务进入empty，6个object和6个observation物理SHA通过，无Parquet，未切换CURRENT。闭包`validation/financial-pit-batch-20260911/batch-13-closure.json` SHA256为`c5217c697dc990ca9992335be42b1a80639897dffe4372d18e5c2cfde3d1517c`。
- 这6个空响应只约束具体公司、报告期和报表API，不能外推为供应商历史为空、修订完整或PIT完整。worker与Beat已恢复；本批与12:20波次等待正常publish-only和Mac单向镜像。

## 2026-09-11 13:35 财务历史、基金持仓与RRG前向边界

- `075e8f2c`新增`fund_portfolio`默认plan-only精确批次，`3bce873b`修复财务准备器跨epoch筛选并关闭runner只读SQLite连接，`63ced924`加入RRG固定观察前向vintage，`ee850c89`让基金持仓按真实上游请求签名跨两代合同去重；Mac、GitHub和云端master均已对齐。相关18项基金批次测试、9项财务测试和10项RRG bridge测试通过。
- 新固定版`data-476b325b6cf6eb83994abdfdb2249a4d40645b24ec1bcc8bfd1789f052a849a7`已由正常发布周期生成并同步到Mac。304011057字节manifest独立重算SHA与release ID一致，含104497个dataset和785065个文件引用，`retained_observations_included=true`。Mac在只读挂载、`--network none`和Token为空条件下成功读取指数权重、基金行情/复权、沪深董秘问答及三张财务表，各3行、0次上游访问。
- 生产authority不存在字面值`history`的财务任务；历史财务叶仍分布在`20260909/10/11`日期epoch。字面`history`准备以0调用停止后，改用最早`20260909`冻结三API各120项。48.771秒完成360次HTTP 200，结果345 done/15 empty、733行；360个object、360个observation和345个Parquet逐实体SHA通过，共13990760字节。闭包`validation/financial-pit-batch-20260911/batch-14-closure.json` SHA256为`35ccda7f1b47d008cd1bde2cf65bd53fc999271136992d9be2811350b91befda`。
- `fund_portfolio`的76181个任务只对应38090个`api_name+params+fields`请求签名；其中14531个签名已有done、7552 empty、7 quality、6 blocked，15994个从未尝试。精确runner显式接受已观察的legacy/current两代合同，只从未尝试的history叶中按current合同优先选择，所有已有attempt或非pending签名均不重放。首批冻结320个唯一签名；账户滑窗使第一个90秒窗口在限速等待阶段停止，已精确提交292次、28项从未调用。新尾清单与28个未尝试task ID完全一致，7.432秒补完；总计320次HTTP 200、227 done/93 empty、33749行，320个object/observation和227个Parquet逐实体SHA通过，共5954931字节，确定性不明调用为0。最终闭包`validation/fund-portfolio-batch-20260911/batch-2-final-closure.json` SHA256为`01d7bc10d5b828d348d717324030405d15d35bbe19dd4df9e86e7014e1af6e29`。
- RRG bridge只把固定观察转换成从Asia/Shanghai观察日次日开始的forward-only候选，并按当前值连续episode处理A-B-A与消失后重现；`retained_observations_included`非严格true时拒绝。真实固定版因中信成员存在empty、ETF基础存在quality而无法证明观察连续性，20260831信号日可用成员和ETF映射均为0，继续`blocked_data`。基金持仓是周期披露，不代表完整ETF日频暴露或PCF；7个quality签名已有完整响应和Parquet，保留空值质量标记待消费端显式处理；6个blocked签名已有2000行以上饱和响应，后续从保存对象制定可证明的分区方案，不能直接把截断结果改成done，也不重复原请求。
- 正常publish-only已生成`data-e7aca25eb25f6b0618925124fb73c084380859148d6cb0dc647687b33485943e`，Mac标准LaunchAgent新增下载7038个文件并完整校验792104项后原子切换本地`CURRENT`。本地307137814字节manifest实算SHA与release ID一致，含105523个dataset且`retained_observations_included=true`。从authority精确attempt导出的两批引用在新固定版逐项闭环：680个object、680个observation、572个Parquet，共1932项、19945691字节，manifest元数据、Mac物理大小和SHA256错误均为0。生产镜像在只读挂载、`--network none`、socket/DNS阻断及两个Token为空条件下读取`fund_portfolio`、`income_vip`、`balancesheet_vip`、`cashflow_vip`各3行、0次上游调用。Worker与Beat恢复健康；完整历史、历史修订、known_at和PIT仍未闭合。新增机器证据为`docs/tushare-fixed-release-e7aca-financial-portfolio-20260911.evidence.json`。

## 2026-09-11 14:28 财务第15批与基金持仓第4批

- 三项只读审计并行完成后均关闭SQLite和SSH进程；真实写入因authority单写锁及账户共享500 rpm滑窗保持串行。安全排空先停Beat，让在途常规任务自然完成，连续两轮确认active/reserved为空后停止专用worker，没有revoke或强杀。首次财务准备路径位于authority内而被防护以0调用拒绝，改在容器`/tmp`冻结后成功；首次基金plan-only因操作人固定了单文件SHA而非组合helper SHA，以0调用、0写入拒绝，随后使用runner返回的组合SHA重跑通过。这两项非阻塞事件未改变任务集合。
- 财务第15批继续最早`20260909` epoch，三张表各120项。360次HTTP 200在49.599秒完成，351 done、9 empty、705行；360个object、360个observation和351个Parquet逐文件SHA通过，共14086535字节。闭包`validation/financial-pit-batch-20260911/batch-15-closure.json` SHA256为`f36b2910188f5ed6487341e2dbfdfae68fe8565f4c7c667b9f166c28f4e6c69c`。
- 基金持仓第4批从准备时13862个eligible唯一签名中冻结240项，全部current-v2、history pristine叶。240次HTTP 200在62.301秒完成，150 done、90 empty、11763行；240个object、240个observation和150个Parquet逐文件SHA通过，共2601585字节。闭包`validation/fund-portfolio-batch-20260911/batch-4-closure.json` SHA256为`51eeb202862cb4a9729b731a7d5b743534ab8d00022b271774f0173027577827`。
- 本轮合计600次确定调用、12468行、1701个唯一物理引用和16688120字节，确定性不明调用为0；没有发布或切换`CURRENT`。Worker与Beat已恢复healthy。收尾时云盘可用225743339520字节，距100 GiB硬保留线还有118369157120字节。文档worker继续等待实际扩盘和峰值headroom复核，不阻塞结构化采集。下一步等待正常publish-only、Mac镜像和1701项固定版成员闭环，同时准备`index_daily`精确批次。机器证据为`docs/tushare-financial-portfolio-batches15-4-20260911.evidence.json`。

### 2026-09-11 financial batch 15 and fund portfolio batch 4 fixed-release closure

- Normal publish-only generated `data-5f796b5046adfec0d3cb98bff41b00c098a87b090b9df7a1aeeb40202b0d2019`; its 312082232-byte manifest contains 106454 datasets and 799038 files with retained observations enabled. The standard Mac LaunchAgent downloaded 6933 new physical files, verified all manifest entries, exited 0, and atomically switched local `CURRENT`.
- The exact-batch export resolved 1701 unique physical references: 600 objects, 600 observations, and 501 Parquet files totaling 16688120 bytes. Manifest metadata, local sizes, and SHA256 values all matched with zero errors.
- The production image, with `--network none`, empty Token variables, and read-only mirror mount, read three rows each from `fund_portfolio`, `income_vip`, `balancesheet_vip`, and `cashflow_vip`, with zero upstream calls. This closes local availability for these batches; complete history, revisions, `known_at`, and PIT coverage remain open. Machine evidence is `docs/tushare-fixed-release-5f796b-financial-portfolio-20260911.evidence.json`.

### 2026-09-11 index_daily exact batch 4

- 在`data-5f796b5046adfec0d3cb98bff41b00c098a87b090b9df7a1aeeb40202b0d2019`固定版、配置、候选清单、任务清单、preparer和helper全部哈希冻结后，plan-only验证240个pristine `history`任务且上游调用为0。保守240次窗口在31.561秒完成，全部HTTP 200，得到217 done、23 empty和34859行，覆盖240个`.CSI`指数代码。
- 240个object、240个observation和217个Parquet共697个唯一引用、8191869字节，逐文件SHA256通过。批次没有发布或切换`CURRENT`；Worker与Beat恢复healthy。云盘可用224923148288字节，距100 GiB硬线还有117548965888字节。697项等待后续正常固定版发布和Mac镜像闭环；完整历史、修订、`known_at`和PIT仍未闭合。机器证据为`docs/tushare-index-daily-batch4-20260911.evidence.json`。

### 2026-09-11 fund price exact batch 11

- 根据并行只读审计，优先继续直接服务RRG价格与复权输入的`fund_daily+fund_adj`。在固定版、SSE开市日、配置、preparer、helper及360个任务ID全部哈希冻结后，plan-only为0调用/0写入；真实批次覆盖2012-10-10至2013-07-10的180个共同交易日，两接口各180次，44.157秒内360次均HTTP 200且全部done，保留100642行。
- 360个object、360个observation和360个Parquet共1080个唯一引用、14633170字节，逐文件SHA256通过；不确定调用0，未发布或切换`CURRENT`。Worker与Beat恢复healthy。云盘可用224954359808字节，距100 GiB硬线还有117580177408字节。1080项等待正常固定版和Mac镜像闭环；RRG的历史分类/成员`known_at`、修订、可交易状态、PCF和完整生命周期仍保持`blocked_data`。机器证据为`docs/tushare-fund-price-batch11-20260911.evidence.json`。

### 2026-09-11 financial exact batch 16

- 财务继续最早`20260909` epoch，`income_vip`、`balancesheet_vip`、`cashflow_vip`各冻结120个pristine叶；manifest、任务清单、配置、preparer和helper均哈希固定，plan-only为0调用/0写入。48.382秒完成360次HTTP 200，各API均112 done/8 empty，合计336 done、24 empty和696行。
- 360个object、360个observation和336个Parquet共1056个唯一引用、13599035字节，逐文件SHA256通过；不确定调用0，未发布或切换`CURRENT`。Worker与Beat恢复healthy。云盘可用224876101632字节，距100 GiB硬线还有117501919232字节。1056项将与指数第4批、基金行情第11批一起等待正常固定版和Mac镜像闭环；完整财务历史、修订、`known_at`和PIT仍未闭合。机器证据为`docs/tushare-financial-pit-batch16-20260911.evidence.json`。

### 2026-09-11 index_daily exact batch 5 gray rollout

- 前四批`index_daily`累计1320次调用全部HTTP 200、零429、零不确定调用，平均476.66 rpm；账户与API gate均已冷却，因此第5批从保守240灰度升至360。固定版、配置、preparer、helper、候选库存和任务清单全部哈希冻结，plan-only为0调用/0写入。44.409秒完成360次HTTP 200，335 done、25 empty，覆盖360个`.CSI`指数代码并保留53687行。
- 360个object、360个observation和335个Parquet共1055个唯一引用、12238140字节，逐文件SHA256通过；未发布或切换`CURRENT`。Worker与Beat恢复healthy。云盘可用224854880256字节，距100 GiB硬线还有117480697856字节。1055项等待正常固定版和Mac镜像闭环；完整指数历史、修订、`known_at`和PIT仍未闭合。机器证据为`docs/tushare-index-daily-batch5-20260911.evidence.json`。

### 2026-09-11 fund_share exact batch 9

- 冻结360个`fund_share` pristine历史叶，沪深各180项，日期覆盖2022-07-27至2023-01-22；manifest、任务清单、配置、preparer和helper均哈希固定，plan-only为0调用/0写入。46.203秒完成360次HTTP 200，246 done、114 empty，保留98699行。
- 360个object、360个observation和246个Parquet共966个唯一引用、9308267字节，逐文件SHA256通过；不确定调用0，未发布或切换`CURRENT`。Worker与Beat恢复healthy。云盘可用224830201856字节，距100 GiB硬线还有117456019456字节。966项与其他`5f796b`后续批次一起等待正常固定版和Mac镜像闭环；完整份额历史、修订、`known_at`和PIT仍未闭合。机器证据为`docs/tushare-fund-share-batch9-20260911.evidence.json`。

### 2026-09-11 post-5f796b five-batch fixed-release closure

- 正常任务`2aa9e7c8-9edb-4752-a364-2a7149f2708b`用172.032秒完成publish-only，原子生成`data-473bf47cb69cb6848bb90e8361572e116ac9db7d29bf2e347af0b88469ad6bf7`。316391184字节manifest含108110个dataset和807538个文件，并包含retained observations。Mac标准LaunchAgent下载8499个物理文件、完整验证807538项、exit 0后原子切换到同一固定版。
- `5f796b`后的五个精确批次共1680个任务、4854个唯一引用：1680个object、1680个observation和1494个Parquet，总计57970481字节。authority哈希、manifest元数据、Mac文件大小和Mac SHA256错误均为0。生产镜像在`--network none`、空Token和只读镜像挂载下读取`index_daily`、`fund_daily`、`fund_adj`、`fund_share`及三张财务表各3行，上游调用0。
- API、Worker和Beat均healthy。云盘可用224113618944字节，距100 GiB硬线还有116739436544字节。本闭包确认指数第4-5批、基金行情第11批、财务第16批和基金份额第9批已可在本地脱离Tushare读取；完整历史、修订、`known_at`、PIT成员、RRG可交易状态和PCF仍未闭合。机器证据为`docs/tushare-fixed-release-473bf-five-batches-20260911.evidence.json`。

### 2026-09-11 fund price exact batch 12

- 固定2012-01-10至2012-10-09的180个共同SSE开市日，`fund_daily`与`fund_adj`各180项；固定版、日历、配置、preparer、helper和360个任务ID全部哈希冻结，plan-only为0调用/0写入。44.271秒完成360次HTTP 200，全部done并保留81121行。
- 360个object、360个observation和360个Parquet共1080个唯一引用、12239245字节，逐文件SHA256通过；不确定调用0，未发布或切换`CURRENT`。Worker与Beat恢复healthy。云盘可用224086990848字节，距100 GiB硬线还有116712808448字节。1080项等待后续正常固定版和Mac镜像闭环；RRG历史分类/成员`known_at`、修订、可交易状态、PCF和完整生命周期仍保持`blocked_data`。机器证据为`docs/tushare-fund-price-batch12-20260911.evidence.json`。

### 2026-09-11 financial exact batch 17

- 财务继续`20260909` epoch，三表各冻结120个pristine叶；manifest、任务清单、配置、preparer和helper均哈希固定，plan-only为0调用/0写入。49.666秒完成360次HTTP 200，各API均113 done/7 empty，合计339 done、21 empty和701行。
- 360个object、360个observation和339个Parquet共1059个唯一引用、13701636字节，逐文件SHA256通过；不确定调用0，未发布或切换`CURRENT`。Worker与Beat恢复healthy。云盘可用224065323008字节，距100 GiB硬线还有116691140608字节。1059项等待后续正常固定版和Mac镜像闭环；完整财务历史、修订、`known_at`和PIT仍未闭合。机器证据为`docs/tushare-financial-pit-batch17-20260911.evidence.json`。

### 2026-09-11 index_daily exact batch 6

- 前五批`index_daily`累计1680次调用全部HTTP 200、零429、零不确定调用，因此保持360次灰度档。固定版、配置、preparer、helper、候选库存和任务清单全部哈希冻结，plan-only明确为0 authority、0凭据、0上游、0写入和0发布。45.783秒完成360次HTTP 200，350 done、10 empty，覆盖360个`.CSI`指数代码并保留56218行。
- 360个object、360个observation和350个Parquet共1070个唯一引用、12288701字节，逐文件SHA256通过；未发布或切换`CURRENT`。Worker与Beat恢复healthy。云盘可用224044765184字节，距100 GiB硬线还有116670582784字节。1070项等待正常固定版和Mac镜像闭环；完整指数历史、修订、`known_at`和PIT仍未闭合。机器证据为`docs/tushare-index-daily-batch6-20260911.evidence.json`。

### 2026-09-11 fund_share exact batch 10

- 发布窗口前只执行一批：冻结360个`fund_share` pristine历史叶，沪深各180项，日期覆盖2022-01-28至2022-07-26；manifest、任务清单、配置、preparer和helper均哈希固定，plan-only明确为0 authority、0凭据、0上游、0写入和0发布。45.227秒完成360次HTTP 200，235 done、125 empty，保留87115行。
- 360个object、360个observation和235个Parquet共955个唯一引用、8336997字节，逐文件SHA256通过；不确定调用0，未发布或切换`CURRENT`。Worker与Beat恢复healthy。云盘可用224030081024字节，距100 GiB硬线还有116655898624字节。955项与另外三批post-`473bf`结果等待17:07后正常固定版发布和Mac镜像闭环；完整份额历史、修订、`known_at`和PIT仍未闭合。机器证据为`docs/tushare-fund-share-batch10-20260911.evidence.json`。

### 2026-09-11 post-473bf four-batch publication gate

- 基金行情12、财务17、指数6和基金份额10共1440项已在authority闭环，合计1284 done、156 empty、4164个唯一物理引用和46566579字节。只读导出再次逐文件验证SHA256；可重建的详细引用清单为754981字节、SHA256 `2ba7e8182c160cc7349d1c501ad56ec54d008dc3a5064d083e3cbb0e02216fac`，四份持久manifest及任务集合哈希已写入机器证据。
- `CURRENT`仍为`data-473bf47c…`，正常发布在2026-09-11 17:07:11 CST后到期。Worker和Beat healthy；发布前不再插入精确批次。尚需正常原子发布、Mac完整镜像、4164引用成员与本地SHA复核，以及断网/空Token/只读挂载离线读回，才能把这四批从“权威端已闭环”提升为“本地固定版可用”。机器证据为`docs/tushare-post-473bf-four-batches-publish-gate-20260911.evidence.json`。
