# 文档入口与用途

本目录保留当前操作指南、实现合同和仍被研究配置引用的冻结来源。部署状态、数据日期和实验结果应查目标实例及其固定版本；指南不作为现场验收证明。历史方案、一次验收报告和重复说明从工作树删除，通过 Git 历史查证，不另建文档归档目录。

## 开发入口与加载边界

| 入口 | 唯一职责 |
| --- | --- |
| [根 README](../README.md) | 项目是什么、本地开发入口和目录导航 |
| [根 AGENTS](../AGENTS.md) | 编码助手需遵守的工作范围、数据边界与关键工程约束 |
| [后端](../backend/README.md) | 服务入口、启动副作用及回测、推理、股票池、撮合、WebSocket 合同导航 |
| [Electron](../electron/README.md) | 前端开发、连接配置、构建和打包边界 |
| [脚本](../scripts/README.md) | 按副作用选择检查、维护和模型注册脚本 |
| [本地策略](../user_strategies/README.md) | 策略文件格式、扫描范围和执行风险 |

Markdown 链接只用于导航，不会把目标全文内联到编码助手上下文。仓库编码规则统一维护在根 `AGENTS.md`，它不导入本目录。各客户端的祖先目录规则、用户配置和显式附加文件仍以实际加载设置为准。

下列 Markdown 是产品运行资源，不是根编码规则：

- [skills](../skills/README.md)：QuantBot 技能经 API 安装到指定工作区，技能正文及参考按任务读取。
- [config/qwenpaw](../config/qwenpaw/AGENTS.md)：`AGENTS`、`SOUL`、`PROFILE` 是 QuantBot 工作区初始化输入；安装入口为 `scripts/quantbot_init.sh`。
- [prompts](../prompts/README.md)：用户复制的请求卡片，唯一源为 `scripts/gen_prompts.py`，前端读取生成的 TypeScript；不保留重复 Markdown 卡片。
- `backend/services/engine/routers/ai_ide/`：`KnowledgeBase` 读取现行策略、Lab SDK 和回测合同，`skill_templates/` 按意图加载模板。这些是产品 AI-IDE 的上下文，不是仓库编码助手默认注入。上游包中的任务描述、工作区说明和许可随对应运行路径保留，不表示已开放所有上游场景。

## 数据、存储与部署

| 指南 | 使用场景 |
| --- | --- |
| [数据写入合同](development-data-contract.md) | 区分 Mac 开发、沙盒、现有业务库与固定研究输入，确定写入目的地 |
| [本地市场数据源](local-market-source.md) | QuantDB、BTC/ETH 日更，固定文件交付、派生计算和失败恢复 |
| [Tushare 归档](tushare-mac-source.md) | 唯一写入者、研究白名单、供数缓存、权限频控与归档迁移 |
| [Tushare 原文与 PDF](tushare-document-storage.md) | 下载解析、OCR staging/ingest、hold、收据式退役和中断恢复 |
| [Binance 产品合同](binance-data-products.md) | 选择产品、资产与时间口径，判断研究准入 |
| [Binance 操作](binance-data-operations.md) | 增量采集、固定发布、扩池和 Qlib/H5 消费验收 |
| [存储与恢复](storage-recovery-20261009.md) | 容量、数据库/快照恢复点及派生计算内存故障 |
| [QuantDB 数据包](QuantDB_数据包解压指南.md) | 在暂存区导入外部数据包，核对挂载和覆盖范围 |
| [部署](部署指南.md) | 区分本地隔离实例、可选首次安装和已有实例维护 |
| [Electron 编译](Electron编译方案.md) | 运行 workspace 命令，定位构建产物和平台打包问题 |

Tushare 离线回归原料放在 `backend/tests/fixtures/tushare/`，保留原始字节及 SHA 证据链，不作为当前权限或完整历史的证明。配置中 `git:<commit>:<path>` 表示历史证据，可用 `git show <commit>:<path>` 查阅；不是可直接打开的本地文件。

## 研究、策略与模型

| 指南 | 使用场景 |
| --- | --- |
| [研究工作台](research-workbench-operations.md) | 创建、审批、运行和停止研究 Agent，核对本节点持久化 |
| [研究登记](research-case-workflow.md) | 固定来源与合同，解释数据准入、退出码和证据阶段 |
| [冻结研究](frozen-research-workflow.md) | 固定计算输入和离线对照，遵守保留段规则与现有隔离限制 |
| [基线运行](quant-baseline-workflow.md) | 使用现有 API 基线，处理响应不明和重复提交风险 |
| [研究数据选择](research-data-priority.md) | 按课题选择数据、合并优先级覆盖、固定发布版本 |
| [研究资料评审](研究方法更新工作流方案.md) | 使用 research_watch 采集/离线重放，评审方法而不直接追收益 |
| [执行与账务](execution-accounting.md) | 核对引擎分流、成交、估值、资金恒等式和风控批次 |
| [RRG 冻结来源笔记](2026-09-05-RRG行业轮动研究笔记.md) | 供 `config/rrg_sector_rotation.json` 和登记脚本复制的原始研究来源；不是当前推荐或未见验证 |
| [策略编写](QuantMind策略编写手册_v2.md) | 模板、Qlib 配置、过滤与自定义选股钩子的统一合同 |
| [Strategy Lab 操作](Strategy_Lab用户手册.md) | 事件式脚本回测、结果解释、模板转换与本地扫描 |
| [Strategy Lab SDK](Strategy_Lab规范.md) | 维护 SDK/HTTP、复现字段、安全与统计诊断边界 |
| [回测费用](回测费用配置说明.md) | 核对佣金、过户费和参与率冲击模型 |
| [模型训练](QuantMind_模型训练完全指南.md) | 配置时间切分、训练任务、注册状态及产物使用 |
| [模型推理](模型推理服务设计与链路文档.md) | 核对模型解析优先级、存储接口与故障路径 |
| [FinBERT](FinBERT%20中文金融情感模型.md) | 安装依赖/权重、配置情感开关并诊断实际使用状态 |

## 外部交易接入

| 指南 | 使用场景 |
| --- | --- |
| [通达信桥](integrations/tdx-bridge.md) | 可选部署、只读诊断、权限副作用及私有凭据配置 |
| [大 QMT 桥](大QMT真单镜像_部署与上线手册.md) | 导出桥包、Windows 启动、连接诊断和独立真单授权 |

接入说明不授予下单权限。实盘、正式数据覆盖、恢复和真实文件删除仍须按目标与影响范围单独授权。
