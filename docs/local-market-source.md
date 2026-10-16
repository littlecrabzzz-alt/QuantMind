# 本地市场数据源运维

用途：维护 Mac 供应商采集 → 固定文件版本 → 本地/云端接收与派生链路。Mac 是唯一日常采集入口；现有云端接收、业务库、队列和研究服务不因远端开发退役而视为已迁移。本文给出编排合同，实际安装状态、版本与截止日必须读取运行回执。

| 数据 | 编排触发（北京时间） | 交付与消费 | 自动范围依据 |
| --- | --- | --- | --- |
| QuantDB / A | 每天 03:00，15 分钟补查/唤醒补跑 | 固定清单校验，分别应用 PG/Qlib/市场分析 | 现有 `quantdb_daily_sync.sync_parquet` 数据集及 L1 OHLCV 补采，不表示所有分钟/Tick 均日更 |
| Binance / BC | 每天 08:15，15 分钟补查/唤醒补跑 | 原始固定 release 校验，分别生成 Qlib/H5 | BTCUSDT、ETHUSDT 已收盘 UTC 日线 |
| Tushare | 独立原生 worker | SSH 私有研究子集缓存 | `config/tushare-local-research-only.json` 的 18 个接口；实际配置需核对 |

Mac 休眠/离线时不采集，消费者保留最后校验版本。联网后补跑不代表全部历史自动完成。Docker 未运行时编排尝试启动 Docker Desktop，最多等 180 秒；失败保留旧数据，下轮继续，不启动研究或开发后端。

## 入口与状态

Mac 项目根目录：

```sh
# 安装/更新会改 LaunchAgent，不是只读检查
python3 scripts/local_market_source.py install
# 会采集、交付并尝试应用；先确认活动任务与节点配置
python3 scripts/local_market_source.py tick
# 明确需要立即补查某一市场才使用 force
python3 scripts/local_market_source.py tick --market A --force
python3 scripts/local_market_source.py tick --market BC --force
```

- 独立源根：`~/Library/Application Support/QuantMind/market-source`；原始目录为 `working/project/data/{quantdb,quantbc}`，与研究沙盒隔离。
- LaunchAgent：`com.quantmind.market-source`；持久客户端：相邻 `market-source-client`；日志：相邻 `logs/market-source.*.log`。采集代码从主树只读挂入隔离容器，不挂业务库/Redis。
- `status.json` 分市场记录采集版本、`cloud_release`、`local_release` 与 `retry_pending`；`A-collection.json`、`BC-collection.json` 是原始采集结果。
- 接收端 `/data/local-market-source/{A,BC}-receipt.json`；本地 A 使用 `.local-dev/QUANTDB_SYNC.json`，本地 BC 有自己的接收回执。必须区分节点，同名文件不是同一状态。
- Tushare 归档、缓存、版本读取及权限恢复见 [Tushare 运维](tushare-mac-source.md)；Binance 产品与手工批次见 [Binance 运维](binance-data-operations.md)。

## 故障按阶段恢复

1. **采集**：供应商错误、权限、磁盘或 Docker 失败时保存原结果；未成功不发布。只对已确认需求使用 force，不用反复重采掩盖下游故障。
2. **发布/传输**：清单固定文件大小与 SHA，验证完整才交付；同内容复用相同市场清单 ID。容量不足、哈希不符保留旧版和失败阶段，不把“SSH 传完”当应用成功。
3. **接收/派生**：A 在行情写锁下记录安装日志并原子换目录；中断按已安装文件继续派生，不反向交换。`installing`、`files_applied` 都不是完成，只有 `applied` 表示该回执的派生步骤结束。
4. **本地应用**：活动任务、文件冲突、后端未启动时保留待应用版本。A 复用沙盒空闲检查与维护窗口，只在必要窗口暂停相关 API/worker；失败后先核对实际服务状态，不操作独立研究容器。
5. **消费**：再验 PG/Qlib 实际日期与固定版本真实查询；上游成功或接收 applied 不证明某个研究已读到该版本，也不证明历史完整或 PIT。

已有任务继续使用冻结输入，不跟随 CURRENT；更新期间业务查询可能仍读旧派生结果，以回执和实际截止日说明。各节点业务数据库不通过市场编排互相覆盖。

## 空间与回退

Mac 保留 300 GiB，Tushare 500 GiB 预警，云端接收保留 100 GiB；传输前还需计算新增载荷和临时/派生峰值。自动轮转限于本编排登记的源中转与受管备份，保留两版及当前/待恢复引用；旧备份、Tushare 全量归档、Binance 原始 release 和研究固定输入不因此获得删除授权。

失败先阻止新的编排准入，等待现有 `.source.lock`/接收锁自然释放，保留日志和回执。不要重新启用云端供应商采集作自动回退。确需回退市场目录时，在行情写锁和相关查询维护窗口使用回执指向的已核验备份，并重新验派生日期；跨版本不能沿用旧 applied 回执。

存储清理、完整业务快照、Redis/PG 故障见[存储与服务恢复](storage-recovery-20261009.md)。APFS 克隆和硬链接共享块，目录逻辑大小不等于可回收空间。

## 不由本链路决定的事项

自动数据接入不启动训练、策略、虚拟盘或实盘；不迁移正在运行的研究。股票/指数/ETF 核心行情优先，新增财务、公告、海外/期货/分钟等范围需要显式变更实际配置与验收；已保存记录和缺口保留。开发/研究数据隔离及留痕见[数据合同](development-data-contract.md)。
