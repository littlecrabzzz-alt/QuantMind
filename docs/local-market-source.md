# 本地市场数据源运维

用途：维护 Mac 供应商采集 → 固定文件版本 → 本机主业务应用与派生链路。Mac 是唯一日常采集与业务运行机器；主业务运行代码位于 `~/Library/Application Support/QuantMind/primary-runtime-*`，Main 工作树用于开发。本文给出编排合同，实际安装状态、版本与截止日必须读取运行回执。

| 数据 | 编排触发（北京时间） | 交付与消费 | 自动范围依据 |
| --- | --- | --- | --- |
| QuantDB / A | 每天 03:00，15 分钟补查/唤醒补跑 | 固定清单校验，分别应用 PG/Qlib/市场分析 | 现有 `quantdb_daily_sync.sync_parquet` 数据集及 L1 OHLCV 补采，不表示所有分钟/Tick 均日更 |
| Binance / BC | 每天 08:15，15 分钟补查/唤醒补跑 | 原始固定 release 校验，分别生成 Qlib/H5 | BTCUSDT、ETHUSDT 已收盘 UTC 日线 |
| Tushare | 独立原生 worker | 本机归档固定版本只读消费 | `config/tushare-local-research-only.json` 的 18 个接口；实际配置需核对 |

Mac 休眠/离线时不采集，消费者保留最后校验版本。联网后补跑不代表全部历史自动完成。Docker 未运行时编排尝试启动 Docker Desktop，最多等 180 秒；失败保留旧数据，下轮继续，不启动研究或开发后端。

## 入口与状态

以下命令使用**已核准且已准备主业务状态**的 Library 主运行快照；将占位路径替换为实际版本。执行前确认该快照的 `.local-primary/READY`、`AUTHORITY.json` 与恢复校验记录有效，且 `quantmind-local` 实例存在。缺少 READY 时停止，不使用脚本的默认项目或其它模式代替。

```sh
PRIMARY_RUNTIME="$HOME/Library/Application Support/QuantMind/primary-runtime-<approved-version>"
bash "$PRIMARY_RUNTIME/scripts/local-primary.sh" status
# 安装/更新会复制客户端并重载 LaunchAgent，不是只读检查
python3 "$PRIMARY_RUNTIME/scripts/local_market_source.py" install --project "$PRIMARY_RUNTIME"
# 会采集并尝试应用；先确认活动任务与本机配置
python3 "$PRIMARY_RUNTIME/scripts/local_market_source.py" tick --project "$PRIMARY_RUNTIME"
# 明确需要立即补查某一市场才使用 force
python3 "$PRIMARY_RUNTIME/scripts/local_market_source.py" tick --project "$PRIMARY_RUNTIME" --market A --force
python3 "$PRIMARY_RUNTIME/scripts/local_market_source.py" tick --project "$PRIMARY_RUNTIME" --market BC --force
```

- 独立源根：`~/Library/Application Support/QuantMind/market-source`；原始目录为 `working/project/data/{quantdb,quantbc}`，与主业务运行数据、研究沙盒隔离。
- LaunchAgent：`com.quantmind.market-source`；持久客户端：相邻 `market-source-client`；日志：相邻 `logs/market-source.*.log`。安装时从显式项目复制客户端；采集容器只读挂载该项目代码，不挂业务库/Redis。核对已安装 ProgramArguments 中的 `--project` 指向主运行快照，不能指向客户端自身或 Main。
- `status.json` 分市场记录 `release_id`、`primary_release` 和当前 `status`；`retry_pending` 表示失败待续。`A-collection.json`、`BC-collection.json` 是原始采集结果，不能代替应用回执。

纸盘就绪 QA（paper-readiness v1，见[后端唯一日更契约](../backend/README.md#唯一日更契约paper-readiness-v1)）：`python3 scripts/paper_readiness_qa.py` 只读核验受管归档行级日期与冻结资产输入，产出 `~/Library/Application Support/QuantMind/market-source/paper-readiness.json`，按固定输入身份缓存在相邻 `paper-readiness-cache/`。逐户 ready/pending/blocked 与原因见该 JSON；canonical CURRENT 或日历/资产身份变化须重新核验，不由 tick 重判。冷准备与复用成本依实际数据量记录，不以 QA green 代替八户 runtime/API/页面验收。
- 主业务 A 的应用回执在主运行快照 `.local-primary/QUANTDB_SYNC.json`，BC 在 `.local-primary/BC_SYNC.json`，BC 内部派生回执为运行数据中的 `data/local-market-source/BC-receipt.json`。沙盒 `.local-dev/QUANTDB_SYNC.json` 不是主业务状态，同名文件不能混用。
- Tushare 归档、固定版读取及权限恢复见 [Tushare 运维](tushare-mac-source.md)；Binance 产品与手工批次见 [Binance 运维](binance-data-operations.md)。

### 主业务目标与客户端版本

`scripts/local_market_source.py` 依据显式项目的 `.local-primary/READY` 选择
`quantmind-local-quantmind`，应用后写 `primary_release`；A 复用
`quantdb_refresh.apply`，BC 复用 `apply_bc`。本指南只适用于这一主业务模式，
不得通过删除 READY、另选项目或重启沙盒来恢复采集。

Main 的编辑不会自动更新主运行快照或持久客户端。按[本地主业务运行](local-primary.md)
安装核准快照后，才从该快照执行上述 install，更新现有客户端与原 LaunchAgent；
不得新增并行采集器。记录已安装脚本 SHA、ProgramArguments、首跑阶段、
`primary_release` 与真实消费查询。安装模板、代码提交或 READY 文件存在本身均不是运行成功证明。

目标修复不代表供应商数据齐全。QuantDB 原有 HTTP410、下载失败和接口/历史缺口
作为独立上游事实保留；分区名最后日期须再验非空行数、代表证券价格及 PG/Qlib/
市场分析实际截止日。Binance 日线按 UTC 收盘时间核验，release 的 end_exclusive
不是最后 bar 日期；既有正确收盘过滤不因时区或目录名猜测而改变。

## 故障按阶段恢复

1. **采集**：供应商错误、权限、磁盘或 Docker 失败时保存原结果；未成功不发布。只对已确认需求使用 force，不用反复重采掩盖下游故障。
2. **发布**：清单固定文件大小与 SHA，完整验证后才供本机应用；同内容复用相同市场清单 ID。容量不足、哈希不符保留旧版和失败阶段，固定文件就绪不等于派生成功。
3. **应用/派生**：A 在本机维护锁下检查冲突，保留备份并原子换目录；中断按已安装文件继续 PG/Qlib 派生，不反向交换。BC 校验原始 release 后生成本机派生结果。`installing`、`files_applied` 都不是完成，只有对应回执的 `applied` 表示该阶段结束。
4. **维护窗口**：活动任务、文件冲突、后端未准备时保留待应用版本。A/BC 复用目标栈的空闲检查，只在必要窗口暂停相关 API/worker；失败后先核对实际服务状态，不操作独立研究容器。
5. **消费**：再验 PG/Qlib 实际日期与固定版本真实查询；上游成功或接收 applied 不证明某个研究已读到该版本，也不证明历史完整或 PIT。

已有任务继续使用冻结输入，不跟随 CURRENT；更新期间业务查询可能仍读旧派生结果，以回执和实际截止日说明。主业务与沙盒数据库不通过市场编排互相覆盖，两个栈不能同时占用 8000。

## 空间与回退

Mac 保留 300 GiB，Tushare 500 GiB 预警；应用前还需计算新增载荷和临时/派生峰值，BC 内部派生另有 100 GiB 余量检查，不能因此降低源端 300 GiB 保护。自动轮转限于本编排登记的源中转与受管备份，保留两版及当前/待恢复引用；旧备份、Tushare 全量归档、Binance 原始 release 和研究固定输入不因此获得删除授权。

失败先阻止新的编排准入，等待现有 `.source.lock`、维护锁及行情锁自然释放，保留日志和回执，不启动第二个采集器作自动回退。确需回退市场目录时，在行情写锁和相关查询维护窗口使用回执指向的已核验备份，并重新验派生日期；跨版本不能沿用旧 applied 回执。

存储清理、完整业务快照、Redis/PG 故障见[存储与服务恢复](storage-recovery-20261009.md)。APFS 克隆和硬链接共享块，目录逻辑大小不等于可回收空间。

## 不由本链路决定的事项

自动数据接入不启动训练、策略、虚拟盘或实盘；不迁移正在运行的研究。股票/指数/ETF 核心行情优先，新增财务、公告、海外/期货/分钟等范围需要显式变更实际配置与验收；已保存记录和缺口保留。开发/研究数据隔离及留痕见[数据合同](development-data-contract.md)。
