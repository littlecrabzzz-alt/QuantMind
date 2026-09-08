# 九个已购买文本接口：契约和采集计划

2026-09-09：在 `codex/tushare-text` 实现纯标准库契约与流式计划生成，尚未在此子任务读取凭据、调用生产 API、下载文件或部署。接入总目标及验收不变，见 [总计划](tushare-integration-plan.md) 和 [任务书](tushare-integration-task.md)。生产权限、完整性和原文验收由主执行者独立记录。

| API / 官方依据 | 历史起点 | 参数 / 返回上限 | 字段与来源注意事项 |
|---|---|---|---|
| [news](https://tushare.pro/document/2?doc_id=143) | 未公布精确日期；文档称超过六年 | 必填 `src,start_date,end_date`，秒精度；1500 行 | 覆盖 sina、wallstreetcn、10jqka、eastmoney、yuncaijing、fenghuang、jinrongjie、cls、yicai；显式请求隐藏字段 channels |
| [major_news](https://tushare.pro/document/2?doc_id=195) | 未公布精确日期；文档称超过八年 | 可选 `src,start_date,end_date`，秒精度；400 行 | 显式请求隐藏 content；9 个中文来源加无来源过滤窗口，避免漏掉样例中的其他来源 |
| [cctv_news](https://tushare.pro/document/2?doc_id=154) | 2017 年，具体首日未知 | 必填 `date=YYYYMMDD`；单次上限未公布 | 保存 date/title/content；代码 1000 行仅是保守截断警报，不能作为供应商承诺 |
| [anns_d](https://tushare.pro/document/2?doc_id=176) | 未公布精确日期 | `start_date,end_date` 日期范围；2000 行 | 保留 ann_date/ts_code/name/title/url 及隐藏 rec_time；url 是待下载证据，不代表 PDF 已保存 |
| [irm_qa_sh](https://tushare.pro/document/2?doc_id=366) | 2023-06，具体首日未知 | 日期 `start_date,end_date`；另有秒级 `pub_start,pub_end`；3000 行 | 文档样例 ann_date 与参数表冲突，采用参数表；区分问题日期、回复时间与首次抓取 |
| [irm_qa_sz](https://tushare.pro/document/2?doc_id=367) | API 文档 2010-10，具体首日未知 | 同沪市问答；3000 行 | 多存 industry；样例代码仅六位，标准化须带交易所依据并保留原值 |
| [npr](https://tushare.pro/document/2?doc_id=406) | 未公布 | `start_date,end_date` 秒精度；500 行 | 不过滤 org/ptype，覆盖未穷举类别；显式请求隐藏 url/content_html，保存全部七字段 |
| [research_report](https://tushare.pro/document/2?doc_id=415) | 2017-01-01 | `start_date,end_date` 日期范围；1000 行 | 不过滤类别/机构/行业；表内十字段全取，额外请求样例出现但表内未列的 file_name，并独立审计支持情况 |
| [monetary_policy](https://tushare.pro/document/2?doc_id=465) | 2001 年，具体首日未知 | `start_date,end_date` 日期范围；1000 行 | 保存 pub_date/title/url/pdf_url/content_html；历史按年，每年约四篇，近期按日复查 |

[官方频次表](https://tushare.pro/document/1?doc_id=290) 给出新闻三接口 400 次/分钟、公告/问答/政策/研报 500 次/分钟、央行报告 200 次/分钟。作为共享账号限速的上界输入，不能为各并行进程分别分配整个额度。账号真实能力仍以安全探测结果为准。权限表称深市问答“25 年”，与 API 页的 2010-10 起点冲突，不能宣称此前无数据；需另做更早区间探测。

`major_news` 明列来源为新华网、凤凰财经、同花顺、新浪财经、华尔街见闻、中证网、财新网、第一财经、财联社。官方样例仍出现其他来源，并把来源列展示为 src_site，契约要求核对真实返回 schema；不把这九个名字当作供应商的穷尽集合。无 src 过滤的交叉采集会重叠，原始对象保留，归一化使用来源与内容身份避免误合并。

## 计划生成与接入接口

`backend/shared/tushare_text_contracts.py` 提供 `TEXT_CONTRACTS`、`TEXT_CONTRACT_NOTES` 和 `iter_text_jobs(config, today)`。生成器不写数据库、不联网，输出 `api_name,params,priority,epoch`。主采集器持久化身份和检查点，并执行限流、重试、动态细分及发布。

配置 `history_start` 或 `text_history_start` 指定所请求的历史范围；可用 `text_history_starts` 逐接口覆盖。配置不是已证实的供应商起点。`text_apis` 缺省全部九接口，生产范围的减少必须显式出现在总台账。无精确起点的接口保留机器可读缺口；允许省略开始日期的接口还会发出配置起点以前的无下界前缀请求。此前缀满页时需先建立更早边界再细分，不能当完整；news 必填开始日期，仍需更早边界探测。

先输出今天及前六日的全部 API/来源窗口（priority 20），再按日期倒序交错历史 API/来源（priority 40）。央行历史每年一个窗口，避免数千个空日请求。`epoch` 对近期为当天 YYYYMMDD，历史为 history；`planning_epoch` 可把近期更新推进至小时/分钟批次。同一近期 epoch 不会自动再次采集，云端应按端点更新周期轮换 epoch。今天仍在形成，不能以一次返回或空结果宣布全天完整。

秒级窗口共享午夜边界，避免依赖未确认的左右包含语义；返回的重复行交给存储层去重。沪深问答近期同时生成问题日期和 `pub_start/pub_end` 回复时间窗口，用于发现旧问题的新回复。动态细分器须识别这两个轴；不能只保留回复轴，否则未回答的问题会丢失。

日期倒序计划会随 today 变化。主执行器不能跨天盲目复用一个位置偏移；必须使用稳定作业身份、接口/来源/日期检查点或固定规划日。新接口/来源加入时也须产生独立计划版本，不能跳过已越过的偏移位置。

## 不完整条件与存储要求

- `required_fields` 保证列存在，`nullable_fields` 只允许单元格缺失，不能把字段缺失解释成完整。行情的正数验证不适用于文本。默认隐藏及额外样例字段并入 fields；未经验证不能静默删字段重试并宣布全字段完成。
- 这些文本端点未提供有保证的唯一 ID。keys 采用时间、标题、正文/URL 等组合；正文变化保留不同记录。主存储还应保留 `_source`（请求来源回退返回来源）、原始行哈希、观察时间及原始 JSON，避免同秒同题的不同报道被覆盖。未知新增列保留原始数据并登记 schema 漂移。
- 满页意味着“可能截断”。秒级接口可递归细分；最小秒仍满则缺口。日期接口到单日仍满时，公告需要完整证券范围（包括基金和固收）；研报需要类别、机构和个股等交叉分区。不能仅按返回中已出现的名称拆分并宣称穷尽。
- `attachment_fields` 包含需归档的原文和 PDF 入口；npr/央行 HTML 还可能含其他附件，后续独立发现。必须分别记录元数据、下载、解析、页码引用、本地镜像，不把链接存在当正文完整。
- 空响应、无权限、源停更、超频、接口错误、隐藏字段不支持、历史边界未证实、坏链、解析失败分别登记；阻碍某个接口时仍推进其他队列。七日复查也不能代替历史修订巡检。

离线验证：`python3 scripts/test_tushare_text_contracts.py`，覆盖九类字段相对目录无遗漏、全部来源/无过滤窗口、闰日/跨日边界、历史起点与未知前缀、近期优先、迟到回复双轴、intraday epoch、错误配置、流式输出。该验证不证明生产权限、API 日期过滤行为或历史完整性。
