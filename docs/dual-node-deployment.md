# QuantMind 双端部署记录

更新：2026-09-08。本文区分已验证状态与尚未实施的迁移，避免把代码同步视为完整应用已上线。

## 已确认的目标

- Mac 与 lzy-vm 双向同步完整源码工作树、未提交代码、文档、Skills 和共享配置，包含 `.env.local`、`config/runtime.env`。
- Mac 会断网：离线修改代码保留在本机，重新连接后同步；同一文件两端同时编辑需要处理冲突，不承诺自动语义合并。
- 数据以 lzy-vm 为唯一权威源。Mac 离线研究基于最后已校验快照，本地新结果在联网登记成功前不是权威结果。
- 数据库、任务队列和调度器不得出现两个并发主节点。机器依赖分别安装；Git 元数据独立维护。

## 已实施并验证

- 云端 SSD：`/dev/vdb`，磁盘 ID `disk-joxd1ee9`，容量 500 GiB，ext4。
- UUID：`3c46a144-f3a3-4250-95ee-e85fb5d8e88a`。
- 挂载点：`/root/data/disk`；初始化后 `df` 显示可用约 467 GiB。
- 修正 `/etc/fstab` 中相对挂载路径为绝对路径；原文件保留于 `/etc/fstab.quantmind-ssd-backup-20260907`。`findmnt --verify` 已无错误；未以重启验证。
- 项目：`/root/data/disk/quantmind/project`，入口软链接 `/root/code/QuantMind`。
- 独立目录：`/root/data/disk/quantmind/volumes`、`backups`、`staging`，顶层目录权限 0700。
- 复用两端现有 Syncthing 服务，新建 `quantmind-code`，类型 `sendreceive`，启用文件监听和 10 个历史版本。原有 Guanlan 文件夹状态未改动。
- `.stignore` 通过 `#include .sync-code-ignore` 加载共享规则；根 `.stignore` 已分别安装到两端。
- 验证 Mac 到云端、云端到 Mac 的临时探针同步；验证 `.env.local`、`config/runtime.env`、关键训练代码和 SQL 升级脚本的两端 SHA-256 相同。密钥文件在云端保持 0600。
- 云端 Git 从本机独立初始化，保留当前浅克隆边界、已有本地分支和当前未提交修改。初始 HEAD 为 `3f3c2f7c77b941cb213097bdb81dc926a60f3d9b`，分支 `codex/dark-mode`；Git 对象连通性检查通过。

## 代码同步范围

同步源码与共享配置；排除 `.git`、依赖、缓存、日志、数据目录和研究产物。保留 `data/upgrade_v*.sql`、`data/stocks` 及 `db/sql` 等源码资源。`.stversions` 已被 Git 忽略，避免历史密钥进入 Git 提交。

Syncthing 的历史版本保存在接收端，不等于应用一致性备份。当前 Git 历史仅完成初始化；后续提交、分支及合并仍需通过 Git 管理，不由 Syncthing 同步。运行中的服务也不会仅因文件同步而自动切换代码版本。

## 仓库是同步和部署配置的来源

- `deploy/dual-node.env`：SSH 别名、SSD UUID、项目真实路径、Syncthing 设备和端口。
- `.sync-code-ignore` / `.stignore`：代码与数据的互斥边界。`.env.local`、`config/runtime.env` 会经加密的 Syncthing 同步，但不提交 Git。
- `scripts/dual_node_sync.py mac|cloud [--apply]`：对照仓库检查/对齐本项目的实际 Syncthing 配置；不会修改其他共享文件夹或新增共享设备。
- `deploy/compose.cloud.yml`：云端资源上限、仅 3080 对公网、SSD 持久化卷、禁用实盘及暂停其他容器。
- `scripts/dual-node.sh`：可续传预复制、镜像传输、前端发布、云端 Compose 和 SSH 访问。
- `scripts/dual-node-cutover.sh` / `dual-node-restore.sh`：停写、备份、最终增量、逐文件校验、数据库恢复及唯一主节点切换。
- `scripts/dual_node_inventory.py` / `deploy/table-counts.sql`：SHA-256 文件清单与全部 PostgreSQL 表的精确行数。
- `scripts/dual_node_snapshot.py`：云端一致性快照及 Mac 校验下载；不覆盖本机已有研究目录，不回灌数据库。
- `deploy/syncthing-ssd.conf`：系统启动时等待 SSD 挂载，已安装到云端 systemd drop-in。
- `python3 scripts/test_dual_node.py`：端口、共享规则、卷路径、训练安全开关的回归检查。

两端配置核对命令（Mac 项目根目录）：

```bash
python3 scripts/dual_node_sync.py mac
ssh lzy-vm 'sudo -n python3 /root/code/QuantMind/scripts/dual_node_sync.py cloud'
bash scripts/dual-node.sh status
```

修改规则后，先核对再执行 `--apply`。如 `.stignore` 被外部工具改动，脚本会报错而非忽略。Git 元数据仍不交给 Syncthing；分支/提交需要单独通过 Git 传递，不能把 `.git` 加回同步。

长时间运行的 shell 脚本启动时会捕获自身内容，避免运行过程中被 Syncthing/编辑器更新后继续读到错位的新文件。这个场景有实际启动子进程并改写脚本的回归测试，不只是静态检查。

## 数据迁移与云端上线进度

当前代码同步及配置核对通过，约 65 GiB 文件数据正在首次预复制。前端已发布，公网 `http://106.54.20.20:3080/health` 已从 Mac 验证可达；这不代表数据库/研究功能已上线。本机仍是当前运行数据所在位置，云端权威源尚未切换。只有 SSD 上的 `AUTHORITY` 标记存在且应用验收通过，才能宣布完成。

后续迁移顺序：

1. 清点所有可变状态，包括 PostgreSQL、Redis、Huntly SQLite/索引、QwenPaw volumes、QuantDB 同步状态、研究结果和模型；制作恢复点。
2. 将数据预复制到 SSD 暂存区；冻结相关写入后执行一致性备份和最后增量校验。数据库底层热文件不参与 Syncthing。
3. 单独配置云端端口、宿主路径和卷位置；关闭 `TRAINING_PAUSE_OTHERS`，保持实盘交易关闭。
4. 云端启动并验证账户、策略、数据版本、模型及研究结果，再切换唯一调度器和两端访问入口。
5. 验证 Mac 离线快照、联网后的增量追赶和结果登记；只有校验及业务验收通过后才宣布迁移完成。

快照去重只对已发布的不可变快照使用 `rsync --link-dest`。活跃数据源始终独立复制，不与快照共享 inode；这一边界已有实际文件修改回归测试。首次快照需要额外约 65 GiB，以后未改变的文件在快照之间复用，不重复占用空间。磁盘可用少于 100 GiB 时拒绝新建快照，不会擅自删除研究历史。

## 首次迁移与恢复约束

```bash
# Mac；预复制可重复执行，只传增量。只允许在云端 AUTHORITY 尚不存在时运行。
bash scripts/dual-node.sh preseed
bash scripts/dual-node.sh images
bash scripts/dual-node.sh web-publish
# 确保云端镜像全部准备好、研究任务已完成后才执行：
bash scripts/dual-node-cutover.sh
```

切换脚本只停止 QuantMind 的写入服务，发现独立研究容器或活动 Celery 任务时拒绝切换。PostgreSQL 用事务一致性 dump 跨 CPU 架构迁移；Redis、Huntly、QwenPaw 停写后迁移。QwenPaw 整卷恢复包含其注册清单，后续技能更新仍只走 `quantbot_init.sh`，不能单独复制技能目录。

初次预复制不删文件。最终停写增量只在明确的数据子目录内对齐删除，被替换/删除的旧文件保留在本次迁移备份的 `displaced/`，不是不可恢复清除。所有文件清单一致、数据库 dump/卷归档校验一致、114 张表的行数一致后才启动云端写入者。目标数据库非空时拒绝覆盖。

备份位置：Mac `logs/dual-node-<UTC>/`；云端 SSD `backups/migration-<UTC>/`。切换失败后写入服务保持停止，先查看日志和云端 `AUTHORITY`，不得在云端已成为主节点后直接重启 Mac 的旧主库服务。

切换会把 Mac 写入容器的自动重启策略改为 `no`，防止重启 Docker Desktop 时复活第二个主节点。Syncthing 不受影响，断网重连后继续同步源码；`preseed` 在切换后会明确拒绝向权威数据目录回灌。

## 两端访问及离线边界

联网时可直接访问云端 3080；也可运行 `bash scripts/dual-node.sh connect`，通过加密 SSH 隧道访问 `http://127.0.0.1:18080`。两种入口指向同一服务、同一数据库。公网当前是 HTTP，没有部署域名/TLS；涉及密码和研究数据时优先使用 SSH 隧道。

Mac 断网不影响云端服务。断网时本机现有数据是截至切换时的离线基线，代码编辑和冻结数据研究可以继续，但云端新数据不可能实时出现在离线 Mac。

权威源切换完成后，在无研究任务的时间主动创建/拉取新快照：

```bash
ssh lzy-vm 'sudo -n python3 /root/code/QuantMind/scripts/dual_node_snapshot.py create'
python3 scripts/dual_node_snapshot.py pull
```

创建快照会先做不停服预复制，然后短暂停止本项目写入容器，完成最终文件校验、PostgreSQL dump 和冷卷归档，最后恢复原来运行的容器。快照仅在全部校验通过后发布。Mac 下载到 `logs/cloud-snapshots/<snapshot-id>/`，校验通过才更新 `latest`；重复下载同一快照只补缺失/变化部分，不覆盖本机原有 `data/`、`results/` 或数据库。研究时使用快照的明确 ID，不能在研究期间切换输入版本。

当前脚本已通过语法检查与去重边界回归测试，但首次云端全量快照/下载尚未验收，也未安装定时刷新。离线研究产物应单独保留，不能直接回灌数据库；自动结果登记尚未实现。不能把这一状态描述成已完成的自动双向数据库同步，或声称离线时仍与云端实时一致。

代码同步不等于运行中的进程自动更新。前端改动用 `web-publish` 构建并发布，旧静态文件保留于云端 `staging/web-*.previous`；后端改动完成核对后，通过仓库里的 `cloud-compose restart` 重启对应服务。
