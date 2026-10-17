# 本地市场数据源运维

用途：维护 Mac 供应商采集 → 固定文件版本 → 本机主业务应用与派生链路。Mac 是唯一日常采集与业务运行机器；主业务运行代码位于 `~/Library/Application Support/QuantMind/primary-runtime-*`，Main 工作树用于开发。本文给出编排合同，实际安装状态、版本与截止日必须读取运行回执。

| 数据 | 编排触发（北京时间） | 交付与消费 | 自动范围依据 |
| --- | --- | --- | --- |
| QuantDB / A | 每天 03:00，15 分钟补查/唤醒补跑 | 固定清单校验，分别应用 PG/Qlib/市场分析 | 现有 `quantdb_daily_sync.sync_parquet` 数据集及 L1 OHLCV 补采，不表示所有分钟/Tick 均日更 |
| Binance / BC | 每天 08:15，15 分钟补查/唤醒补跑 | 原始固定 release 校验，分别生成 Qlib/H5 | BTCUSDT、ETHUSDT 已收盘 UTC 日线 |
| Tushare | 独立原生 worker | 本机归档固定版本只读消费 | `config/tushare-local-research-only.json` 的 18 个接口；实际配置需核对 |

Mac 休眠/离线时不采集，消费者保留最后校验版本。联网后补跑不代表全部历史自动完成。Docker 未运行时编排尝试启动 Docker Desktop，最多等 180 秒；失败保留旧数据，下轮继续，不启动研究或开发后端。

## 入口与状态

采集使用显式核准、已经存在于本机的 Docker 镜像和只读代码快照；不查询业务容器来猜镜像，也不拉取镜像。`--project` 是唯一 formal primary 应用目标，`--collector-project` 是独立核准采集代码（省略时等于 `--project`），`--collector-image` 在 tick/install 必填。目标未具 `.local-primary/READY`，或 READY 已在 adopt 后出现但 formal DB/Redis/backend 尚未可用时，仍可采集和发布；未应用版本只记录 `awaiting-primary`，不操作业务库、沙盒或云端。READY 只放行就绪检查，不代替 `AUTHORITY.json` 与恢复验收。

```sh
PRIMARY_RUNTIME="$HOME/Library/Application Support/QuantMind/primary-runtime-<approved-target>"
COLLECTOR_CODE="$HOME/Library/Application Support/QuantMind/primary-runtime-<approved-code>"
COLLECTOR_IMAGE="sha256:<approved-local-image-id>"
# 安装/更新会复制客户端并重载原 LaunchAgent，不是只读检查。
# --no-start 用于先暂存客户端/plist；不 bootstrap、不触发 RunAtLoad。
python3 "$COLLECTOR_CODE/scripts/local_market_source.py" install --project "$PRIMARY_RUNTIME" \
  --collector-project "$COLLECTOR_CODE" --collector-image "$COLLECTOR_IMAGE" \
  --secrets "<approved-secrets-directory>" --no-start
# 会采集并在 READY 后尝试 safe apply；先确认活动任务与本机配置。
python3 "$COLLECTOR_CODE/scripts/local_market_source.py" tick --project "$PRIMARY_RUNTIME" \
  --collector-project "$COLLECTOR_CODE" --collector-image "$COLLECTOR_IMAGE" \
  --secrets "<approved-secrets-directory>"
# 明确需要立即补查某一市场才附加 --market A --force 或 --market BC --force。
```

- 独立源根：`~/Library/Application Support/QuantMind/market-source`；原始目录为 `working/project/data/{quantdb,quantbc}`，与主业务运行数据、研究沙盒隔离。
- LaunchAgent：`com.quantmind.market-source`；持久客户端：相邻 `market-source-client`；日志：相邻 `logs/market-source.*.log`。安装时从显式核准的采集代码复制客户端及现有 apply 依赖；ProgramArguments 持久化 `--project`、`--collector-project`、`--collector-image`、`--secrets`。采集容器只读挂代码和原有 runtime.env，仅源目录可写，不挂业务库/Redis。`--host` 已移除，不保留云端默认。核对应用目标不能指向客户端自身或 Main。
- `status.json` 分市场记录 `collection_status=collected`、`publication_status=published`、`release_id`，本地应用独立记录 `apply_status`。待应用版本在 primary 未就绪时 `status` / `apply_status` 为 `awaiting-primary`，`apply_wait_reason` 给出原因，正常返回 0；真实采集/发布/应用失败为 `retry_pending`、`error`、`failed_stage`，返回 2。只有 safe apply 成功才写 `primary_release` / `apply_status=applied`；已有 applied 游标不等于服务当前在线。历史 `cloud_release` / `local_release` 留作证据及轮转保护，永不充当本轮主库 applied。`A-collection.json`、`BC-collection.json` 是原始采集结果，不能代替应用回执。

纸盘就绪 QA（paper-readiness v1，见[后端唯一日更契约](../backend/README.md#唯一日更契约paper-readiness-v1)）：`python3 scripts/paper_readiness_qa.py` 只读核验受管归档行级日期与冻结资产输入，产出 `~/Library/Application Support/QuantMind/market-source/paper-readiness.json`，按固定输入身份缓存在相邻 `paper-readiness-cache/`。逐户 ready/pending/blocked 与原因见该 JSON；canonical CURRENT 或日历/资产身份变化须重新核验，不由 tick 重判。冷准备与复用成本依实际数据量记录，不以 QA green 代替八户 runtime/API/页面验收。
- 主业务 A 的应用回执在主运行快照 `.local-primary/QUANTDB_SYNC.json`，BC 在 `.local-primary/BC_SYNC.json`，BC 内部派生回执为运行数据中的 `data/local-market-source/BC-receipt.json`。沙盒 `.local-dev/QUANTDB_SYNC.json` 不是主业务状态，同名文件不能混用。
- Tushare 归档、固定版读取及权限恢复见 [Tushare 运维](tushare-mac-source.md)；Binance 产品与手工批次见 [Binance 运维](binance-data-operations.md)。

### 主业务目标与客户端版本

`scripts/local_market_source.py` 不依赖任何业务容器来启动采集。镜像通过本地
`docker image inspect` 解析为固定 ID，`docker run --pull never` 拒绝缺失镜像，
不自动切换 `quantmind-dev` 或远端。未来 formal READY 有效时 A 继续复用
`quantdb_refresh.apply`，BC 继续复用 `apply_bc`，成功后写 `primary_release`。
就绪检查只在采集/发布之后执行：本地 Docker inspect formal DB/Redis 健康状态及 backend
运行/健康状态，再复用 `local-primary.sh` 的本机 `/health` 只读探测，不执行 DB 写探测。
缺失容器、服务停止、健康检查未就绪或 API 不可用只延后应用；既有
`files_applied` 恢复允许被 safe apply 故意停止的 backend，DB/Redis 仍须健康，
再由原恢复流程继续派生。原主栈空闲、挂载、锁、冲突、容量和派生检查保持不变。

Main 的编辑不会自动更新主运行快照或持久客户端。按[本地主业务运行](local-primary.md)
准备核准代码快照，再通过现有 install 更新原客户端和原 LaunchAgent，不新增采集器。
install 与 tick 争用同一个 `.source.lock`；锁被占用或 LaunchAgent 有活动 pid 时拒绝安装，
不替换活动代码、不 bootout writer。默认安装仍 bootstrap；`--no-start` 只在确认 idle 后
卸载旧 idle label 并写客户端/plist，保留 `RunAtLoad=true` 的正常调度定义，稍后由操作者 bootstrap。
记录已安装脚本 SHA、ProgramArguments、首跑阶段、采集/发布与应用回执及真实消费查询。
模板、提交、安装成功或 READY 文件存在本身都不是运行成功证明。

目标修复不代表供应商数据齐全。QuantDB 原有 HTTP410、下载失败和接口/历史缺口
作为独立上游事实保留；分区名最后日期须再验非空行数、代表证券价格及 PG/Qlib/
市场分析实际截止日。Binance 日线按 UTC 收盘时间核验，release 的 end_exclusive
不是最后 bar 日期；既有正确收盘过滤不因时区或目录名猜测而改变。

## 故障按阶段恢复

1. **采集**：供应商错误、权限、磁盘或 Docker 失败时保存原结果；未成功不发布。只对已确认需求使用 force，不用反复重采掩盖下游故障。
2. **发布**：清单固定文件大小与 SHA，完整验证后才供本机应用；同内容复用相同市场清单 ID。容量不足、哈希不符保留旧版和失败阶段，固定文件就绪不等于派生成功。
3. **应用/派生**：A 在本机维护锁下检查冲突，保留备份并原子换目录；中断按已安装文件继续 PG/Qlib 派生，不反向交换。BC 校验原始 release 后生成本机派生结果。`installing`、`files_applied` 都不是完成，只有对应回执的 `applied` 表示该阶段结束。
4. **维护窗口**：主库未就绪保留固定发布版本并记录 `awaiting-primary`；同日重查和以后 READY 就绪不会因等待应用重复采集，新的每日采集槽照常判断。活动任务、文件冲突、后端未准备时既有 safe apply 保留待应用版本。A/BC 复用目标栈空闲检查，只在必要窗口暂停相关 API/worker；失败后先核对实际服务状态，不操作独立研究容器。
5. **消费**：再验 PG/Qlib 实际日期与固定版本真实查询；上游成功或接收 applied 不证明某个研究已读到该版本，也不证明历史完整或 PIT。

### 单 writer 受限验收

先只读确认原 source label idle、无活动采集及足够 300 GiB 余量；不得中断下载或现有 writer。
在允许的运行窗口用 `install --no-start` 暂存核准版本，核对原 plist 与客户端 SHA；
READY 缺失时只执行一次上述 tick 命令并附加 `--market BC --force`，仍使用现有
BTCUSDT/ETHUSDT、5 天采集和既有 UTC 收盘过滤，不另建根、collector、供应商重试或并发。
核验 BC collection 回执、固定 bundle 清单/文件 SHA、最后真实 bar 收盘时间和
`collection_status=collected` / `publication_status=published` / `apply_status=awaiting-primary`，
确认没有新增主库应用回执、sandbox/cloud 动作。采集后正常 tick 不加 force，以确认不重采同日成功槽；
完成后由操作者 bootstrap 原 plist 恢复正常全市场调度。formal READY 后再在安全维护窗口
核验既有 safe apply、`primary_release`、PG/Qlib/H5 及消费者查询，不能把 awaiting-primary 当 applied。


已有任务继续使用冻结输入，不跟随 CURRENT；更新期间业务查询可能仍读旧派生结果，以回执和实际截止日说明。主业务与沙盒数据库不通过市场编排互相覆盖，两个栈不能同时占用 8000。

## 空间与回退

Mac 保留 300 GiB，Tushare 500 GiB 预警；应用前还需计算新增载荷和临时/派生峰值，BC 内部派生另有 100 GiB 余量检查，不能因此降低源端 300 GiB 保护。自动轮转限于本编排登记的源中转与受管备份，保留两版及当前/待恢复引用；旧备份、Tushare 全量归档、Binance 原始 release 和研究固定输入不因此获得删除授权。

失败先阻止新的编排准入，等待现有 `.source.lock`、维护锁及行情锁自然释放，保留日志和回执，不启动第二个采集器作自动回退。确需回退市场目录时，在行情写锁和相关查询维护窗口使用回执指向的已核验备份，并重新验派生日期；跨版本不能沿用旧 applied 回执。

存储清理、完整业务快照、Redis/PG 故障见[存储与服务恢复](storage-recovery-20261009.md)。APFS 克隆和硬链接共享块，目录逻辑大小不等于可回收空间。

## 不由本链路决定的事项

自动数据接入不启动训练、策略、虚拟盘或实盘；不迁移正在运行的研究。股票/指数/ETF 核心行情优先，新增财务、公告、海外/期货/分钟等范围需要显式变更实际配置与验收；已保存记录和缺口保留。开发/研究数据隔离及留痕见[数据合同](development-data-contract.md)。
