# 存储、备份与服务恢复

用途：维护仍在运行的业务服务、恢复点和市场接收端。远端开发退役不等于这些服务或数据库已迁走；本页不宣称任何节点当前健康、timer 正在运行或备份仍最新。先核对实际挂载、可用块、容器与活动任务，再决定维护范围。市场阶段回执见[本地市场数据源](local-market-source.md)。

## 先区分存活、就绪与数据新鲜度

在现有云端项目宿主，使用带 SSD/资源覆盖层的入口，只运行只读检查：

```sh
sudo -n bash scripts/dual-node.sh cloud-compose ps
sudo -n bash scripts/dual-node.sh cloud-compose exec -T quantmind \
  python3 -S /app/scripts/check_storage_readiness.py
```

readiness 检查 `/`、`/data` 空闲空间、PG `SELECT 1` 及 Redis AOF/RDB 持久化状态；JSON `ready=false` 与非零退出应视为失败。默认就绪磁盘阈值只有 2 GiB（可由 `QM_STORAGE_MIN_FREE_BYTES` 改），不是采集/备份所需的 100/300 GiB 恢复余量。HTTP 200、容器 running、Redis PING 或 timer active 都不是业务就绪或完整备份证明。

后续核对市场回执、PG/Qlib 实际日期和固定 release 查询；派生成功不等于权限、历史或 PIT 缺口全部解除。不要因 Redis 系统故障而持续消费/输出相同错误，也不要关持久化保护来恢复表面健康。

## 容量与可删除边界

- Mac 源端保留 300 GiB，Tushare 500 GiB 预警；云端接收和快照保留 100 GiB。预算包括新/变更载荷、临时写入、DB/卷导出、备份峰值和运行增长，不只比较目录总大小。
- `scripts/storage_guard.py` 协调快照/接收准入，载荷上传前预检，运行中继续监测并留写入缓冲。容量拒绝时保留当前版，不通过降低阈值或清空队列绕过。
- 源中转和接收/回滚副本依完成标记与当前回执轮转；接收端只自动处理新代码标记 `MANAGED-v2` 的已完成副本，保留两版及受保护版本。未知目录、未完成版本和历史备份不自动删。
- 业务库、研究结果、固定输入、唯一完整恢复点、迁移前 QuantDB 备份和其他应用文件不属于临时运输清理。不得就地删除 COMPLETE 快照内的文件。
- 用文件系统可用块衡量回收，不能累加硬链接/APFS 克隆逻辑大小。历史空间/吞吐测量不承诺今天能释放多少或备份多久。

本地已完成副本可通过现有显式计划入口审查：

```sh
python3 scripts/storage_maintenance.py plan --out /absolute/new-cleanup-plan.json
# 审核每个路径、引用与备份后，才允许 apply；确认值为计划文件原字节 SHA256
python3 scripts/storage_maintenance.py apply \
  --plan /absolute/new-cleanup-plan.json --confirm VERIFIED_PLAN_SHA256
```

该工具保护 latest、状态引用及保留版，执行前重建计划核对；它面向完整副本目录，不适用于附件逐文件退役。PDF 只能遵守[附件生命周期合同](tushare-document-storage.md)，不能直接调用通用目录删除。

## 完整快照与恢复点

仅在确认服务所在宿主、SSD UUID、AUTHORITY 和维护窗口后操作。云端项目宿主：

```sh
# 有写入暂停，不是日常开发前置检查
sudo -n python3 scripts/dual_node_snapshot.py create
# 只列旧完整快照候选；--apply 才删除
sudo -n python3 scripts/dual_node_snapshot.py prune
```

Mac 拉取现有完整恢复点：

```sh
python3 scripts/dual_node_snapshot.py pull
```

不要恢复旧 `com.quantmind.snapshot-pull` 作为行情日更；行情由 Mac 本地源交付。`pull` 只写快照缓存，不覆盖 `.local-dev`，不回灌业务库，也不改运行中研究输入。无需恢复跨端开发 handoff 才能解释备份用途。

快照 `snapshot-v2` 的复制、增量和校验采用同一范围，排除可再取得的 incoming/backups 运输载荷，保留回执及研究输入；旧清单按旧范围校验。在线预复制后，检查活动研究/协调器并暂停此前运行的写入者，捕获数据库和冷卷，恢复写入后独立全量校验/压缩，成功才发布 COMPLETE/latest。只在不可变快照间复用硬链接，不能连接到活跃数据树。

失败保留 `.building`，不推进 latest。常规异常和信号通过 finally 恢复此前运行的写入者，断电/SIGKILL 不保证；先核对实际服务状态再续跑。不要把 `.building` 当废物：排除正在运行的作业、取得快照锁、确认不是唯一恢复材料后才能另行决定清理。旧范围暂存与新规则不兼容时应保留排查，不能静默复用。

`create` 会执行完整快照轮转，不是无副作用预检；选择无活动研究窗口。`pause_seconds` 只计至发出恢复启动命令，不表示所有服务已就绪，需独立验收。`pg_restore --list` 只证明归档可读，不是整库恢复成功。需要恢复时在隔离卷/临时库先验完整性、schema、角色与业务数据，再单独批准切换；仓库没有可无脑执行的生产整库回滚命令。

## ENOSPC、Redis 与服务参数

1. 停止新增大规模复制/接收准入，保留当前回执、日志、磁盘/挂载和失败阶段；确认根盘与数据盘，防止把未挂载目录当数据盘。
2. 先找有完成标记、可重取且未被引用的运输副本。不得删除唯一归档、数据库卷、原 AOF 或唯一恢复点。必要扩盘需在云厂商侧明确授权；先核对实际设备/分区，再选择文件系统工具，不照抄历史 `/dev/vdb` 命令。
3. Redis `INFO persistence=ok` 不证明旧 AOF 全文件可回放。保存原件及 SHA，在副本上检查；不要直接执行会截断后段的 `--fix`。修复方案需对比可用 RDB 时点与可丢失业务范围，隔离、无网络验证重建、数据摘要和完整 AOF 后再安排切换；自然 TTL 过期需单独解释。
4. 重建/重启前核对真实镜像、环境、挂载和活动任务，保留私有配置差异。`cloud-compose` 的默认文件不保证与现场完全相同，敏感 override 只存受控私有目录。只更新相关服务，不重启整个栈或独立研究容器。
5. 恢复后验 PG、Redis 持久化、应用 readiness、接收续跑、PG/Qlib 日期及原固定研究输入，不能靠容器重启次数掩盖故障。

如需追查 2026-10-09 Redis 修复的原始材料，历史私有位置为云端 `/root/backups/quantmind-storage-recovery-20261009-1322/redis-repair/`，旧 AOF 留存名含 `.appendonly-before-repair-20261009`；这是历史取证定位，不是当前备份承诺，不授权删除或直接恢复该时点。

## QuantDB 派生内存故障

`fill_pg_from_parquet` 仅扫描所需分区，采用 DuckDB 256 MB、单线程及逐标的分块读取；价格指标仍需 160 日预热。每批日期事务 upsert，失败整批回滚。DuckDB 预算不限制 Python RSS、子进程或整个容器；OOM 后先检查实际容器预算与批次回执，不以减少历史/删标的来伪装恢复。

Qlib 由 `QlibDataBuilder.build_all` 在同盘临时目录构建，持文件锁，校验字段长度、日期索引及最新覆盖后整体原子替换；失败保留旧缓存。局部构建用独立输出目录，不先发布新日历，不覆盖运行中的固定研究输入。确认作业结束后才能清理强杀遗留临时目录。

恢复按原行情锁与阶段检查点续跑，分别验 Parquet→PG 行数/值、Qlib 日历/特征和实际消费者。前复权/除权回退、缺事件表、非核心源 partial 及 Tushare source_lagged 仍独立报告，不能由最新日价格正确推断历史收益已通过验收。
