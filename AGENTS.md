# QuantMind 开发约定

## 当前方式

- 2026-10-16 起，以 Mac 本地为唯一源码与开发源，不再在远端开发。
- 本地开发不再要求双端预检、`handoff`、远端 Git 对齐或 Syncthing 双向协作。旧文档中的这些流程已退役；与本文件冲突时以本文件为准。
- 远端开发退役不代表现有服务和数据库已迁移。远端部署、维护或数据操作须属于明确任务，不随普通开发自动执行。

## 工作与数据安全

- 先查看本次涉及文件及已有修改；保留用户和其他任务的工作，不批量覆盖、回退或顺手提交无关文件。
- 优先扩展已有页面、API、任务和存储入口，不另建重复系统。并行或实验性修改可用独立 worktree，但它不自动隔离数据库、配置和容器挂载。
- 本地测试使用已确认的沙盒或临时输出，不加载生产凭据、不覆盖权威数据。操作页面/API 前确认实际后端节点，不能凭 `localhost` 判断写入目的地。
- 改配置前核对文件和挂载去向；密钥不写进代码、文档或日志。数据库、采集检查点、固定研究输入和历史成果不得因清理或初始化而删除。
- 市场原始数据由 Mac 唯一采集；云端只消费已校验版本，不恢复旧云端采集或反向镜像。不将本地业务库整体覆盖到云端。
- 重启前确认相关任务空闲，只操作受影响服务；文档修改不重启服务。提交、发布和数据迁移分别处理，实盘开关保持关闭。

## 本地开发

后端为 Python/FastAPI，入口 `backend/main_oss.py`；前端为 Electron/React/TypeScript，位于 `electron/`。以下命令均在仓库根目录按需执行，不是连续启动步骤。

```bash
bash scripts/local-dev.sh status                       # 查看当前模式与服务
bash scripts/local-dev.sh start core                   # 已初始化沙盒：启动本地后端
npm run dev:react --workspace=electron -- --host 127.0.0.1  # Web；已有 Vite 时不重复启动
npm run dev --workspace=electron                       # Electron，替代上面的 Web 入口
npm run typecheck                                      # 前端改动后运行
python backend/run_tests.py unit                       # 使用隔离的测试数据与配置
```

首次初始化不要覆盖已有卷。Python 修改需在相关任务空闲时执行 `bash scripts/local-dev.sh restart-backend`；研究 worker 用 `restart-research-worker`。前端使用 Vite HMR，无需为每次修改重建镜像。纯 Python 改动无依赖变化时也不重建镜像。

## 关键代码约束

- Python 使用 ruff，行宽 88；验证改动路径和实际行为，不以编译通过代替验收。
- 策略增删改查统一走 `backend/shared/strategy_storage.py`；外部报单前先本地持久化。
- 成交/委托时间使用 `TIMESTAMPTZ`、aware UTC，写入复用 `backend/shared/utc_datetime.py`，JSON 带 `Z`，不混用 naive UTC 和上海墙钟。
- 股票代码跨层转换使用 `backend/shared/stock_utils.py` 的 `StockCodeUtil`；前端用 `electron/src/utils/portfolioUtils.ts` 的 `normalizeStockCode`。QuantDB 为 `600036.SH`，Qlib 为 `sh600036`，PG/大多数 API 为 `SH600036`，不得手写切片混用。
- 不同时启动内嵌和独立业务 Celery worker。`research-worker` 使用独立研究队列，不能用全局 `brpop` 客户端数量判断重复。
- Qlib 是派生缓存，复用 `QlibDataBuilder.build_all` 的校验与原子发布，不先单独替换日历。数据验收检查实际截止日、派生结果和页面，不把下载成功当作可用。
- QuantBot 技能更新走 `scripts/quantbot_init.sh`，不手工复制技能目录。

## 投资研究

- 先固定输入版本和截止日；最后六个日历月只在完整策略、参数和评价冻结后作最终验证，开发、选品、调参和全样本预处理不得使用保留段。
- 已看过或用于调整策略的数据不再视为独立验证。具体课题的日期、接触清单和实现状态按其冻结方案读取，不在本文件复制。
- 研究保留输入快照或 `release_id`、代码版本、参数、任务 ID 和产物证据；历史研究、虚拟盘和实盘分开标明。

## 按需查阅

只在任务涉及时读取对应文档，不默认遍历 `docs/` 或 `coordination/`。

| 任务 | 入口 |
| --- | --- |
| 行情采集、应用、恢复 | [本地数据源](docs/local-market-source.md)；Tushare 细节见 [Mac 归档](docs/tushare-mac-source.md) |
| 研究工作台、研究 worker | [研究工作台操作](docs/research-workbench-operations.md) |
| R01 冻结边界 | Mac 本地 `../投资学习与研究/课题/R01-data-split-policy-v1.json`，仅相关研究时读取 |
| 历史部署、迁移和恢复 | [部署记录](docs/dual-node-deployment.md)、[数据规范](docs/development-data-contract.md)；其中双端开发流程已退役，不能直接照搬执行 |
| 长期任务记录与历史证据 | [记录约定](coordination/README.md)，普通开发不要求写记录 |

调度参数、部署状态和验收结果放在对应配置、功能文档或任务记录中；本文件只维护现行通用约束，规则变化时替换旧规则，不追加互相覆盖的历史段落。
