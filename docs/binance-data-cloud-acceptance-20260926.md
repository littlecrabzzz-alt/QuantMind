# 币安数据云端发布与日更验收（2026-09-26）

已完成代码集成、固定版本云端发布、真实后台页面/API 验证和 BTC/ETH 日更启用。实际运行代码为 `bd5f2782729a60db6210bc41e9b96d17a1f8df4f`；其后验收文档提交不涉及运行代码。结构化证据见 [验收 JSON](binance-data-cloud-acceptance-20260926.json)，接入操作见 [运行说明](binance-data-operations.md)。

## 数据、页面与研究输入

| 层级 | 验收结果 |
| --- | --- |
| BTC/ETH 云端原始日线 | 各 3,327 行，共 6,654 行；2017-08-17 至 2026-09-25（UTC）；缺口、重复、未收盘均为 0 |
| 云端 CURRENT | `binance-20260926T052342682336Z-69ea91b2d8` |
| Manifest SHA-256 | `0793a67fdbb09c44e2e1f338057ccb607bb0320a9e52e645586a03649750ce15` |
| QuantBC 管理页 | 显示 2/2 已同步：日线、交易对信息；展示当前 release、UTC 和真实截止日；未实现的数据集不提供同步入口 |
| 认证 API | catalog、BTC 预览和调度配置均返回 200；BTC 预览仅 1 行，原生 `amount == quote_volume`，版本与 CURRENT 一致 |
| Qlib / H5 | 同版本构建成功，H5 6,654 行；真实 `D.features` 读取最近 7 天 × 2 币的收盘价、成交额和一日收益率，与原始数据逐值比对通过 |
| 固定研究输入 | 新数据准备任务固定新版本；较早的测试任务仍固定 `binance-20260926T051012327557Z-d4e064872e`；原始 release 哈希不变 |
| AAPLB | 独立 `tokenized_equity_spot` 目录，59 行（2026-07-29 至 09-25），590 个量价值、236 个时间点与原始 Parquet 一致；CryptoAdapter 明确拒绝将其当普通加密现货 |
| Mac 沙盒 | 仍保留首次固定版本 `binance-20260926T031215207598Z-42a749f1ae`，6,654 行；没有云端 Binance 新版本自动回传链路 |

云端数据目录为 `/data/quantbc`、`/data/binance-tokenized-equity`（宿主位于权威项目 `data/`）。初次传输在 staging 严格核对文件清单与 SHA-256 后原子发布，没有回灌业务库。传输生成的 AppleDouble 元数据文件经 magic 核对后仅在 staging 清理，数据文件未改动。

## 自动更新与重复执行

通过现有管理员 API 保存 BC 配置：每天 **08:15 Asia/Shanghai**、`days=5`、数据集 `daily_forward` / `instrument_detail`、`with_qlib=true`。实际点击页面“保存定时配置”后，`with_qlib` 保持 true；其他市场配置逐项未变。

- 自然调度任务 `5ca4be66-8dff-4089-abe3-66498d7b78d5`：北京时间 13:10 补派，40.67 秒完成，采集与 Qlib 均成功；随后分钟检查没有再次自动派发。
- 数值口径迁移任务 `1207f682-fb1c-4512-b285-9fe3b26c8865`：由实际页面触发，自动识别旧数值合同并重取全部已存历史；48.89 秒完成，发布上述新版本。
- 重复增量任务 `fc53b986-6ba6-43fb-aa35-32f96bf19171`：26.94 秒完成，`unchanged=true`、`revised_rows=0`、release 未变，Qlib 成功。

短窗口日更在长停机后仍从已存末日接续；相关 17 天停机恢复用例通过。调度每天最多自动派发一次，失败后当日需查明原因再手动重试，并非自动无限重试。AAPLB 未启用日更。

## 数值口径修复

首次云端增量发现 BTC 9 月 23 日原始响应完全相同，但 Mac/Linux 的 pandas 数值解析出现 1 ULP 差异。经济数值现统一从原始十进制字符串经过 Python float 转为 binary64，并在 manifest 标记数值合同。旧合同升级会完整回采；缺口拒绝发布，不能用旧解析行填洞。

全历史迁移中的 2,236 行变化全部为成交额字段 1—2 ULP 的归一化：BTC 1,457 行，ETH 779 行。原始十进制经济值变化为 0，OHLC、基础成交量、成交笔数及收盘边界均未改变。6,654 行全部找到且校验了原始响应；16 行来源哈希变化由响应分页长度改变导致，对应原始 K 线完全相同。旧版本 3,330 个文件仍与既存 manifest 相符。

## 版本与服务验证

- 最终后端相关测试 **95 passed**；前端调度保存测试 2 passed；类型检查和生产构建通过。
- 双端源码交接于运行版本通过：7,328 个同步文件，摘要 `29f1a8f1564936b17dbd17333ee7e92548f4d77a76257b905c607b2e80cf5763`。
- 云端仅重载 API / 通用 market worker 并发布 Web；研究 worker、research-agent 和原有调度 beat 未重启。最终相关服务健康检查通过。Mac 沙盒后端已重载。
- `ENABLE_CRYPTO=false`、`VITE_ENABLE_CRYPTO=false`、`ENABLE_REAL_TRADING=false`；只验收数据准备与读取，没有启动策略研究、回测或交易。
- 历史回填仍为 `point_in_time_verified=false`；`available_at` 是日线闭合的理论下界，不能证明当年实际收到时间。

云端完整运行证据保存在 `/data/maintenance/binance-data-20260926/`。本机截图为 `output/playwright/quantbc-cloud-20260926.png`、`output/playwright/quantbc-preview-20260926.png`；本机机器可读原始验收输出位于 `output/binance-data-20260926/`。

## 后续扩展标的

当前需要明确的代码/配置变更，尚无页面一键扩池。新增普通币种先审核产品和交易规则，再用新目录建立包含完整目标清单的数据池，补齐上市以来历史、发布新 release，并通过数据及 Qlib/H5 消费验收后切换新任务的默认输入与日更配置。只采入新币不会自动改变 BTC/ETH 调度池。已有研究继续读取原来的固定版本。

股票代币需独立核验底层证券映射、转换比例和公司行动；股票永续还需要资金费、标记价、指数价与合约生命周期。真正的 A 股、美股优先复用 QuantDB / QuantUS 入口，分别验证交易日历、复权和退市标的覆盖。这些类别各自验收，不能仅靠同名 ticker 合并。
