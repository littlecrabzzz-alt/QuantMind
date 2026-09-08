# Tushare 首批数据接入准备

2026-09-08。范围与全量目标沿用 [接入计划](tushare-integration-plan.md)。本次实现的是目录审计、有限样本探测、不可变原始返回与镜像校验；尚未完成历史回填、标准化 Parquet、定时增量和研究数据发布。

进展：已完成 10 个实际请求、13110 行原始数据留存和云端/Mac 的无上游连接读取验收，详见 [首批实测报告](tushare-first-batch-20260908.md)。下文账号记录和准备步骤保留原始核查时点，实际接口结果以该报告为准。

## 当前证据与阻塞

- 当前官方数据目录共 263 个唯一文档条目，全部记录于 `config/tushare-catalog.json`，含原始页面哈希、文档链接、字段名、权限与覆盖状态。227 个条目提取了接口名和输出字段；36 个为分类页或特殊说明，保留 `manual_review_required`。这不是“263 个可调用 API”，也不是全站所有隐藏接口的穷尽证明。
- 每个条目都保持 `permission_status=unprobed`、`coverage_status=not_ingested`。字段提取包含表中默认不返回的字段；特殊参数、数据源枚举、独立授权、停更/别名仍需人工登记。刷新只更新公开目录快照，不覆盖未来采集作业的状态。
- 用户已提供购买情况：当前 10100 积分，另有 6 类独立权限、合计 9 个 API，详见下表。已按用户授权从剪贴板将 `TUSHARE_TOKEN` 写入主工作树被 Git 忽略的 `config/runtime.env`；Syncthing 同步后，两端整份配置和 token 一致，云端 `quantmind` 容器通过现有安全入口可读取，两端文件权限均为 0600。核验仅输出布尔结果，没有记录 token 或其指纹。账号授权以用户提供的信息为依据，尚未以真实接口响应逐项验证。
- 首批准备 9 个请求：日历、中信行情、中信成分 Y/N、ETF 基础列表 L/D/P、ETF 日线和复权因子。可显式指定一个代表 ETF 与报告期增加第 10 个持仓请求；样本不限定最终覆盖范围。
- 本次只在独立 worktree 与临时目录测试；没有改写 QuantDB、RRG 工作流记录，没有启动调度器或重启服务。

## 账号权限记录

来源：用户在本次接入对话中提供的已付费账号页面内容，2026-09-08 记录。此处只保存非密钥的授权信息；目录中的 `permission_status=unprobed` 保持不变，不能用购买记录替代逐接口、逐数据源探测。

| 积分组成 | 获取方式/日期 | 到期日 |
|---|---|---|
| 8000 | 购买，2026-09-08 | 2027-09-08 |
| 2000 | 其他方式，2025-12-05 | 2026-12-05 |
| 100 | 新用户注册，2025-12-05 | 页面未提供 |

当前合计 **10100**，达到 10000 积分档、未达到 15000 档。若没有其他积分变化，2000 积分到期后预计剩余 **8100**，因此需要 10000 分的接口应记录授权到期边界；不要把当前权限固化成永久权限。100 分没有提供到期日，不据此断言永久有效。

| 已购买的独立权限 | 对应接口 | 到期日 |
|---|---|---|
| 沪深董秘问答 | `irm_qa_sh`、`irm_qa_sz` | 2027-09-08 |
| 新闻资讯 | `news`、`major_news`、`cctv_news` | 2027-09-08 |
| 公告数据 | `anns_d` | 2027-09-08 |
| 政策法规库 | `npr` | 2027-09-08 |
| 券商研报 | `research_report` | 2027-09-08 |
| 央行货币政策执行报告 | `monetary_policy` | 2027-09-08 |

接口映射对应本次官方目录核对结果；子来源、字段、频次、历史时间范围及 PDF 可下载性仍需实测。无需再次购买这些已提供购买记录的权限；探测报错时先检查参数、token、授权生效时间与单独频控。

## RRG 的验收缺口

| 数据层 | 已核对的供应商能力 | 仍须验收 |
|---|---|---|
| 中信一级价格 | `ci_daily` 有日线接口，但官方描述已注明不再披露开、高、低、量、额，字段表仍保留这些列 | 实际样本中的 `open` 非空且有效；固定分类名单、全部行业及至少 318 个预热交易间隔；缺开盘价不能通过次日开盘执行契约 |
| 行业历史成分 | `ci_index_member` 提供 `in_date/out_date`，需要分别请求 Y 与 N | 当前成员的空 `out_date` 合法；历史覆盖、分类版本、公告/当时已知时间没有自动得到证明；不能把首次抓取时间倒填成历史 known_at |
| ETF 历史池与交易 | `etf_basic` 区分在市/退市/待上市；`fund_daily`、`fund_adj` 提供价格与因子 | 退市日期、历史池完整性、复权一致性、停牌与真实成交条件；日线量单位为手、额为千元，不能直接当股/元 |
| ETF 持仓与映射 | `fund_portfolio` 有公告日、报告期、持仓市值 | start/end 是报告期过滤；持股权重分母是股票市值，不能假定基金净资产或把部分披露归一化成完整敞口；PCF 和历史可交易池另验收 |

以上层级在全部通过以前，RRG 继续 `blocked_data`。这次工具输出 `sample_ok` 只说明有限响应通过字段检查，并不是价格数值、历史完整性或 PIT 验证通过。

官方依据：[中信行情](https://tushare.pro/document/2?doc_id=308)、[中信成分](https://tushare.pro/document/2?doc_id=373)、[ETF 基础信息](https://tushare.pro/document/2?doc_id=385)、[基金日线](https://tushare.pro/document/2?doc_id=127)、[基金复权](https://tushare.pro/document/2?doc_id=199)、[基金持仓](https://tushare.pro/document/2?doc_id=121)、[HTTP 协议](https://tushare.pro/document/1?doc_id=40)。

## 本地准备和隔离验证

在候选 worktree 根目录执行，不启动 Compose、不加载生产凭据：

```bash
python3 scripts/test_tushare_intake.py
python3 scripts/tushare_intake.py probe \
  --catalog config/tushare-catalog.json --date 20260907 \
  --fund SH510300 --period 20260630 \
  --output /tmp/tushare-rrg-preparation.json
```

不带 `--execute` 时仅生成请求清单，不读 token、不请求数据 API。`--fund` 接受内部前缀式代码，只在供应商请求边界转码；原始返回保留供应商代码与未知字段。标准化层尚未实现，不把供应商后缀代码写入内部业务表。

刷新全目录不需要 token（访问公开文档，四个并发读取者）：

```bash
python3 scripts/tushare_intake.py catalog --output /tmp/tushare-catalog-new.json
```

先审查新旧条目差异与解析失败，再替换仓库快照，不能把无 schema 的页面静默丢弃。目录提取结果不直接驱动数据调用；组合保存/删除等接口不会被自动调用。

## 安全配置与云端第一次探测

Token 通过已有 `backend.shared.runtime_secrets` 写入被 Git 忽略的共享 `config/runtime.env`。用户在主工作树终端可交互输入（不回显、不进入 shell 历史或报告）：

```bash
python3 -c 'from getpass import getpass; from backend.shared.runtime_secrets import set_secret; value = getpass("Tushare token: ").strip(); assert value, "empty token"; set_secret("TUSHARE_TOKEN", value)'
```

不要把 token 发到聊天或放在命令行参数中。若已保存在其他文件，只提供文件路径。共享配置不保存机器专属数据路径/角色。

候选代码合并、源码同步并通过双端预检后，核对云端 `quantmind` 的角色 `authority` 与 `/data` 实际挂载源为 SSD 权威项目的 `data`；在云端宿主使用现有入口：

```bash
sudo -n python3 scripts/dual_node_check.py --node cloud
sudo -n bash scripts/dual-node.sh cloud-compose exec -T quantmind \
  python3 /app/scripts/tushare_intake.py probe \
  --catalog /app/config/tushare-catalog.json --date 20260907 \
  --fund SH510300 --period 20260630 \
  --output /data/tushare/probe-report.json --execute
```

日期改成已确认的最近交易日；ETF 与报告期只是代表样本。脚本还会检查角色、容器与 `/data` 挂载，但这些检查不能替代宿主 SSD UUID 和挂载源的预检。现有容器可以执行新增脚本，不要求重启服务。

采集固定使用通过证书验证的 `https://api.tushare.pro`，禁止自动重定向和继承代理环境；需要代理的网络另做明确配置与测试，不降级 HTTP。每个请求超时 30 秒，间隔 3 秒，只尝试一次。空返回、权限错误、传输错误、字段缺失、可能截断分别报告；2002 按官方协议记录权限问题，其他上游错误保持通用 API 错误。样本不自动重试，不推进回填水位。官方未列明上限的日历/持仓使用保守探测阈值，清单明确标识。

## 云端留存和 Mac 镜像

云端 `/data/tushare` 对应宿主 `/root/data/disk/quantmind/project/data/tushare`：

- `objects/<sha256>.json`：原始返回字节，相同内容复用对象；上游意外回显 token 时先脱敏并标记。
- `observations/<id>.json`：不含 token 的请求参数、请求/抓取时间、对象哈希及检查结论。修订和再次抓取保留新观察记录，不覆盖旧对象。
- `releases/probe-<id>/manifest.json`：请求与结果清单，所有对象落盘后才发布。只是样本证据，不能登记为研究可用数据集。

镜像使用 SSH/rsync 单向从云端拉取到新的独立 Mac 目录；不使用 Syncthing，不依赖 API 的 8000 隧道，不覆盖旧 `data/results` 或活动沙盒。先拷贝所选清单，再按清单拉取对应 observations/objects；数据规模扩大后用增量文件列表与断点续传。复制期间不得暴露为固定研究输入。

校验下载目录（只读）：

```bash
python3 scripts/tushare_intake.py verify \
  --root /path/to/isolated/tushare-mirror --release-id probe-实际ID
```

校验对照清单检查观察记录哈希及每个对象哈希；缺失、损坏、非法路径失败。清单本身需通过受信任 SSH 通道获得，哈希不提供独立数字签名。校验通过只表示传输完整，仍保留请求失败数与 `blocked_data`。正式批量镜像命令、只读沙盒挂载和故障续传验收待有真实 release 后完成，不能把夹具测试算作双端同步验收。

## 紧接的工作

1. 配置 token，云端跑首批样本并审查权限、实际字段、空值、条数上限及历史范围。决定缺失中信开盘价的补充来源；不擅自修改 RRG 成交假设。
2. 用确认的行业/ETF 全历史名单规划分区；处理权限未知、满页拆分、重试账本与完整性对账，再回填。全局源枚举、9 个文本 API、隐藏字段和其他市场继续按总计划逐项展开。
3. 发布标准化数据及质量清单，验证真实云端到 Mac 的增量镜像，并以固定 release 做 RRG 三层独立验收。
4. 大批量回填前按下一批增量、30 天增长、备份峰值加至少 100 GiB 余量计算容量，不足时扩容云盘；本次未扩容。
