# 日程/指数公告3 + 因子库2：纯候选

基线092dedf；仅纯合同/惰性规划，无注册、权限探测、启用、采集或生产变更。263+13目录义务不缩减，原scope其余接口仍待独立批次；不包含p_save/delete等写接口。

| Family / API | 官方页 | 完整输出列 / 文档上限 | 合法请求与日期轴 |
|---|---|---|---|
| calendar_extra / eco_cal | [233](https://tushare.pro/document/2?doc_id=233) | 8 / 100 | date、start_date/end_date、country/currency/event；date与time分离，时区未说明 |
| calendar_extra / cn_schedule | [461](https://tushare.pro/document/2?doc_id=461) | 5 / 3000 | 只有m YYYYMM和title；输出month及计划publish_date，不能添加日/范围参数 |
| calendar_extra / idx_anns | [460](https://tushare.pro/document/2?doc_id=460) | 5 / 1000 | ann_date、start_date/end_date、src；公告日不是指数调样生效日 |
| factor_library / factor_list | [486](https://tushare.pro/document/2?doc_id=486) | 4 / 未给数字；称一次全列表 | factor_name、asset_type、factor_type；全量快照不传日期 |
| factor_library / factor_value | [490](https://tushare.pro/document/2?doc_id=490) | 4 / 6000 | ts_code或factor_name至少一个，加trade_date/start_date/end_date；自动规划只用实际发现factor_name |

26列当前全部默认Y，无隐藏N列；仍显式完整fields。模块保留逐字段类型/描述、输入必选性、HTML SHA及逐字段未实测缺口；新增未知列和空值须保留，不因文档只有26列过滤响应。所有权限均unprobed：前三者文档门槛分别2000/2000/6000积分；后两者因子库独立权限个人2000元/年、机构20000元/年，值页提及5000积分试用，不能由10100积分或已购新闻公告权限推定已授权。未公布每分钟/日配额，30rpm只是保守运行上限。

## 未来接线接口

- `CALENDAR_EXTRA_CONTRACTS`、`iter_calendar_extra_jobs(config,today,identifiers=None)`、`calendar_extra_prerequisites(...)`；配置`calendar_extra_apis`和`calendar_extra_history_start`（字符串或API映射），兼容`history_start`。
- `FACTOR_LIBRARY_CONTRACTS`、`iter_factor_library_jobs(...)`、`factor_library_prerequisites(...)`；对应`factor_library_apis`、`factor_library_history_start`。默认是否启用由未来registry负责，本批不会启用任何family。
- `factor_library_factors`必须来自真实factor_list观察的记录，至少含原样`factor_name`与`asset_type`，保留历史观察而非只取最新列表。没有factor_id列。只有无跨资产重名的STK名称自动规划；非STK/跨资产名称产生明确gap，不猜资产、不送不存在的asset_type到factor_value。列表中的描述不得当程序执行。当前文案202因子/9类别不可作为冻结全集或预置种子。
- 因子值自然键`factor_name,ts_code,trade_date`；列表键`factor_name,asset_type,factor_type`。日历键`date,time,currency,country,event`；日程键`month,publish_date,title,issuing_org,data_api`；公告键`ann_date,source,title,url,type`。全部保留不同源行，仍不能证明同值重复的业务multiplicity。未添加强制request_identity列：初始请求只有一个日期/月/真实因子名称维度，因子名称也是输出自然键；未来滤参比较必须逐观察核实响应与原请求。
- 因子值来源证券只接历史A股含退市/T与观测新增代码，保留`source_ts_code`；不能把未来IDX/ETF/CB混进股票namespace。6000饱和仅允许合法ts_code扇出，当前股票列表不能证明历史证券全集。
- 未来registry和固定reader需使用准确默认日期轴：eco_cal=`date`、cn_schedule=`publish_date`（请求仍为m）、idx_anns=`ann_date`、factor_value=`trade_date`；factor_list无源日期，使用观察快照，不能伪造trade_date。通用date_children对eco_cal的`date`及cn_schedule的月参数需专项核实后接线。

## 时间、历史与饱和边界

未知下界不填演示日期，也不宣称配置19900101就是实际最早。未配置时只生成近期；已配置时先近期、再显式历史，任务epoch/priority复用既有协议。所有日粒度扫描含周末，不能套A股交易日过滤海外经济事件。

- eco_cal近期今日前6天至后7天；idx_anns今日前6天至今日；都是初始全来源日请求，避免把文档四指数公司或手选两个国家当永久全集。经济事件未来7天是有界请求范围，不证明更远未来不存在数据。
- cn_schedule近期前月/本月/次月；历史按合法m逐月，到近期边界前月结束。配置起点在月中仍请求完整所在月，不偷偷丢该月较早发布项。未来更远月份、旧版日程更改仍待覆盖核查。`data_api`可能是“待上线”，只保存字符串，不动态调用或自动注册。
- 因子值近期7日与历史不重叠，日内逐实际名称惰性展开；列表每epoch一次全快照，无日期历史任务。新增因子需依赖通用发现快照/历史追赶流程；仅近期重拉不能补旧因子定义、下架历史和历史修订。
- eco100、公告1000在单日仍可能饱和；国家/货币/事件或src是合法额外过滤，但历史过滤全集未知，未实现二级拆分。日程月3000只有title可再过滤，其全集未知，不能日二分。列表10000只是本地保护、不是实际cap；名称/资产/类别筛选无法自行证明未遗漏。因子6000单因子/单股/单日饱和继续阻塞，无offset/limit/page。
- 原始value/pre_value/fore_value为字符串，可含百分比/K/B/T/空值；因子单位、复权方式、版本、财务数据可得时点和更新时区未充分说明，不能直接推为PIT研究准入。idx_anns保留url附件义务，但本候选没有取得正文/嵌套附件，不能据标题重构行业成员。

## 486目录定点修正证据（父后续负责）

公开原文在Mac `/tmp/tushare-calendar-factor-docs/486.html`；对应`.json`保存DocParser表格。真实输出表头为`名称 | 类型 | 默认显示 | 描述`，后面4行是`factor_name,asset_type,factor_type,factor_desc`。

误识别说明表头`分类名 | 中文名称 | 因子数量 | 说明`，行形如`Alpha101 | Alpha101 量价因子 | 31 | …`，总计行不是字段。随后9组算法说明表头是`序号 | 因子名称 | 算法逻辑`，行首为1、2等数字，也不是输出列。应以真实schema表识别，不应只靠名称正则；数字头在其他真实行情表可合法。

旧13字段 = 上述4字段 + `Alpha101,Growth,Liquidity,Momentum,Quality,Reversal,Risk,Size,Value`。精确差集：应删除这9个说明类别；新增字段为空。本提交不改catalog/parser，测试只接受此已知差集或修正后的零差集，不接受其他漂移。官方原文SHA见下（不因目录修正重写原始证据）。

`486.html SHA256 799b1716dd674500e499bee73be4015307df014c16064219e751bbbfb45650f2`

验证：`python3 -B scripts/test_tushare_calendar_factor_contracts.py`，9项离线测试（socket/DNS禁止），含26字段、合法参数、闰年/跨年/月初尾、历史无重叠、真实名称与资产冲突、未知权限/历史/cap缺口。纯候选通过不等于已接入。

## Runtime候选（基线79f4498 + pure5aa26e1 + parser f024021）

已接入registry、两family PLANNERS/前置gap、来源发现、规范化及固定reader；默认`enable_calendar_extra=false`、`enable_factor_library=false`，本提交不修改配置。没有probe、启用、生产写入或部署。镜像安装复制项由父单独集成。本节更新“未来接线”状态，但实际权益、历史全集、附件正文与PIT缺口仍未通过真实验收。

- `factor_library_factors`仅来自factor_list原文中`factor_name + asset_type`身份，去除重复身份但不改大小写、名字或资产类型；定义文本修订不重置规划名字流，原文/Parquet仍保留完整定义和修订。值接口输出不能补出不存在的asset_type，因此不会反向伪造列表发现。
- `factor_library_stocks`是独立历史股票发现集合，含既有历史/退市/T、technical来源和自身合法STK源代码；不扩大旧stocks族。值只接受T?六位.SH/SZ/BJ规范成交易所前缀并保留source_ts_code；外国/未知拼写保留原始响应并要求schema核查，不能误归A股。calendar和factor_list中的标签不参与证券规范化。
- 原26列继续要求presence，包括缺失列判schema_gap；允许非身份源空值，不把正常空前值/预测值变成失败。eco保留date非空，schedule保留month非空，ann保留ann_date非空；列表保留factor_name/asset_type非空，值保留factor_name/ts_code/trade_date非空。自然键之外的不同全行保留，数值与单位不重算。
- 仅股票code的factor_value请求合法，原文和固定reader已覆盖；如果factor_list空/拒权而code-only值可用，现阶段自动值规划仍等待实际列表身份。明确保留`code_only_discovery_gap`，样本可读不等于自动可跑。待真实权益审计再决定有证据的code-only历史分片，不能由已注册状态或观察到名字猜资产。
- 默认日期轴已按上表实现；factor_list默认None，日期筛选拒绝，没有伪造trade_date。eco/index range使用既有连续日二分；schedule m-only不可日二分。单日/单股/月末饱和保持blocked，所有原文和观察保留。
- idx_anns url接既有文档登记入口；测试只验证登记调用，不做网络下载。链接正文/附件仍未probe，不能把登记或标题当归档完成。data_api始终为返回数据，不执行接口发现/调用。
- 新family配置、名称/资产发现与股票饱和发现不会改变旧family签名；因子规划只冻结实际name/asset依赖，饱和股票集合保持实时。默认关闭和重复规划幂等已验证，未改通用历史游标、预算、next_job/tick/publish或schema版本。
- catalog486过时gap已改成修复证据note，原差异事实保留；运行测试基于f024021，避免enqueue重新加入错误9列。

Python3.10：本批9纯 + 8运行 = 17项通过；运行包含26全列原文→Parquet→固定读取、空值/未知列/修订、独立发现、旧签名、code-only、5种饱和真实执行路径（HTTP MockTransport）和附件登记。3.10全套初跑592项，8个旧测试使用`date.fromisoformat('YYYYMMDD')`报兼容错误，涉及7份未修改的历史测试；不是本批runtime通过的替代证据，父单独修复后统一重跑。日志Mac `/tmp/tushare-calendar-factor-runtime-full310.log`，本批通过日志`/tmp/tushare-calendar-factor-related310.log`，改动方法/旧测试未变证据`/tmp/tushare-calendar-factor-runtime-scope.json`。
