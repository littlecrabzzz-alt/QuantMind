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
