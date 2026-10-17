# 存储、备份与服务恢复

用途：维护 Mac 单机主业务服务、本地恢复材料与市场派生数据。Main 是开发源码，主业务使用 `~/Library/Application Support/QuantMind/primary-runtime-*` 中已核准的代码快照、该快照下 `.local-primary/project` 和 `quantmind-local_*` 独立卷。先核对实际挂载、可用块、容器与活动任务，再决定维护范围；本文不把代码安装或标记文件当作服务健康、备份完整或数据最新的证明。市场阶段回执见[本地市场数据源](local-market-source.md)。

## 先区分存活、就绪与数据新鲜度

在本机使用已准备实例的主运行快照，只运行只读检查：

```sh
PRIMARY_RUNTIME="$HOME/Library/Application Support/QuantMind/primary-runtime-<approved-version>"
bash "$PRIMARY_RUNTIME/scripts/local-primary.sh" status
docker exec quantmind-local-quantmind \
  python3 -S /app/scripts/check_storage_readiness.py
```

readiness 检查 `/`、`/data` 空闲空间、PG `SELECT 1` 及 Redis AOF/RDB 持久化状态；JSON `ready=false` 与非零退出应视为失败。默认就绪磁盘阈值只有 2 GiB（可由 `QM_STORAGE_MIN_FREE_BYTES` 改），不是采集与派生所需的容量余量。HTTP 200、容器 running、Redis PING 或 LaunchAgent 已加载都不是业务就绪或完整备份证明。

后续核对市场回执、PG/Qlib 实际日期和固定 release 查询；派生成功不等于权限、历史或 PIT 缺口全部解除。不要因 Redis 系统故障而持续消费/输出相同错误，也不要关持久化保护来恢复表面健康。

## 容量与可删除边界

- Mac 保留 300 GiB，Tushare 500 GiB 预警；BC 内部派生另有 100 GiB 余量检查，不代替源端保护。预算包括新/变更载荷、临时写入、DB/卷导出、备份峰值和运行增长，不只比较目录总大小。
- `scripts/storage_guard.py` 提供受管操作的容量准入与运行期监测，保留写入缓冲；不是所有本机写入都自动受其保护。容量拒绝时保留当前版，不通过降低阈值或清空队列绕过。
- 源中转和市场回滚副本依据完成标记、引用与回执轮转；自动清理只限代码明确登记的受管副本，保留规则依实际工具及参数。未知目录、未完成版本和历史备份不自动删。
- 业务库、研究结果、固定输入、唯一完整恢复点、QuantDB 备份和其他应用文件不属于临时副本清理。不得就地删除 COMPLETE 快照内的文件。
- 用文件系统可用块衡量回收，不能累加硬链接/APFS 克隆逻辑大小。历史空间/吞吐测量不承诺今天能释放多少或备份多久。

本地已完成副本可通过现有显式计划入口审查，使用明确项目避免误读沙盒引用：

```sh
python3 scripts/storage_maintenance.py plan \
  --project-root "$PRIMARY_RUNTIME" --out /absolute/new-cleanup-plan.json
# 审核全部路径、引用与恢复材料后，才允许 apply；确认值为计划原字节 SHA256
python3 scripts/storage_maintenance.py apply \
  --project-root "$PRIMARY_RUNTIME" \
  --plan /absolute/new-cleanup-plan.json --confirm VERIFIED_PLAN_SHA256
```

该工具保护 latest、它实际读取的状态引用及保留版，执行前重建计划核对；当前引用扫描不覆盖主业务 `.local-primary` 的全部状态，因此计划不是删除授权，必须额外核对 `AUTHORITY.json`、`QUANTDB_SYNC.json`、`BC_SYNC.json` 与冻结输入引用。不能把目录分配字节数直接当作可回收空间。工具面向完整副本目录，不适用于附件逐文件退役；PDF 只能遵守[附件生命周期合同](tushare-document-storage.md)。

## 恢复材料与校验

这里仅列本机已有恢复材料的校验合同，不提供未经实现验证的本地主业务完整备份创建命令，也不把安装代码快照或沙盒初始化当作备份。新的完整备份、首次恢复或重建流程需另行核准实际工具、数据范围和维护窗口；不得借此改写现有库、READY 或 AUTHORITY。

对已经保存在本机的完整快照，可从 Main 执行现有离线校验：

```sh
python3 scripts/dual_node_snapshot.py verify --root /absolute/verified-snapshot
```

该 `verify` 重算归档 SHA 与运行文件清单，不连接供应商、不启动业务或研究，也不恢复数据库。`COMPLETE`、`VERIFIED` 或 latest 指针存在本身不代替重新校验。`snapshot-v2` 清单范围排除可再取得的 incoming/backups 临时载荷，但保留回执及研究输入；旧清单按其原范围校验，不得静默变更口径。只在不可变副本间复用硬链接，不能连接到活跃数据树。

失败保留 `.building`、日志、原件和实际阶段，不推进当前恢复点。排除正在运行的作业、取得相关锁、确认不是唯一恢复材料后，才能另行决定清理；不能用“未完成”推断文件无价值。

`pg_restore --list` 只证明归档可读，不是整库恢复成功。恢复验收必须在隔离卷/临时库核对完整性、schema、角色、逐表行数与内容摘要、sequence、关键业务数据及文件清单，再单独批准切换；不能只凭容器能启动写 READY。现有已准备主业务实例的状态与启停入口见[本地主业务运行](local-primary.md)；该入口不代表已具备通用的本地首次恢复或重建流程。

## ENOSPC、Redis 与服务参数

1. 停止新增大规模复制/应用准入，保留当前回执、日志、磁盘/挂载和失败阶段；确认 Mac 数据目录与 Docker Desktop 卷实际所在磁盘，防止把错误目录当恢复目标。
2. 先找有完成标记、可重取且未被引用的临时副本。不得删除唯一归档、数据库卷、原 AOF 或唯一恢复点。若需扩容，先核对实际 APFS 可用块、Docker Desktop 磁盘容量与宿主空间，不照抄其它文件系统的分区命令。
3. Redis `INFO persistence=ok` 不证明旧 AOF 全文件可回放。保存原件及 SHA，在副本上检查；不要直接执行会截断后段的 `--fix`。修复方案需对比可用 RDB 时点与可丢失业务范围，隔离、无网络验证重建、数据摘要和完整 AOF 后再安排切换；自然 TTL 过期需单独解释。
4. 重建/重启前核对已安装主运行快照、真实镜像、环境、挂载和活动任务，保留私有配置差异；不从 Main 默认 Compose 启动另一套主业务。仅在核准窗口处理相关服务，不重启整个栈或独立研究容器。主业务与 `local-dev.sh` 沙盒不能同时占用 8000。
5. 恢复后验 PG、Redis 持久化、应用 readiness、行情应用续跑、PG/Qlib/H5 日期及原固定研究输入，不能靠容器重启次数掩盖故障。

## QuantDB 派生内存故障

`fill_pg_from_parquet` 仅扫描所需分区，采用 DuckDB 256 MB、单线程及逐标的分块读取；价格指标仍需 160 日预热。每批日期事务 upsert，失败整批回滚。DuckDB 预算不限制 Python RSS、子进程或整个容器；OOM 后先检查实际容器预算与批次回执，不以减少历史/删标的来伪装恢复。

Qlib 由 `QlibDataBuilder.build_all` 在同盘临时目录构建，持文件锁，校验字段长度、日期索引及最新覆盖后整体原子替换；失败保留旧缓存。局部构建用独立输出目录，不先发布新日历，不覆盖运行中的固定研究输入。确认作业结束后才能清理强杀遗留临时目录。

恢复按原行情锁与阶段检查点续跑，分别验 Parquet→PG 行数/值、Qlib 日历/特征和实际消费者。前复权/除权回退、缺事件表、非核心源 partial 及 Tushare source_lagged 仍独立报告，不能由最新日价格正确推断历史收益已通过验收。
