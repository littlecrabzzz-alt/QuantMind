# QuantMind 双端部署记录

更新：2026-09-08。数据迁移已完成；开发规范见 `docs/development-data-contract.md`，日常验收入口为 `python3 scripts/dual_node_check.py`。本文保留迁移历史并区分已验证与未实现的边界。

## 2026-09-08 开发前验收补充

- 主容器上限按用户要求提高至 **12 GiB**（Compose 与实际 Docker 均确认），训练子容器维持独立 4 GiB 预算；因子查询上限 4 GB，OHLCV 补给按请求日期裁剪。
- PostgreSQL CPU 上限由 1 核提高到 2 核，已在线应用并同步到 Compose；内存仍为独立 1 GiB 上限。
- 浏览器兼容层不再误判为 Electron。生产 Web 与 Mac Vite 3000 均通过真实登录，使用同一个云端后端；网络失败不再清除用户保存的服务器地址或自动切到本地旧库。
- 真实单股推理：`SH600519`、输入日 `2025-06-30`，约 30.56 秒完成；数据库运行记录 `run_20250630_f53c2974` 为 `completed`、`signals_count=1`。主容器此次峰值约 5.86 GiB，OOM 计数 0。这不是策略收益有效性证明。
- 幂等写入验收：同一测试自选股 POST 两次只产生一条记录，从 18080 写入、8000 开发入口读取一致；仅本次带标记的测试记录已删除，原记录未修改。可复跑 `python3 scripts/verify_migration_api.py --write-probe`，密码交互输入、不写入报告；加 `--predict` 会额外保留一次真实推理记录，不自动重试非幂等推理请求。
- 市场分析/RSS/个股终端/回测中心/模型训练与管理/推理/投研/技能/QuantBot 页面已浏览；此次页面切换捕获的 API 错误为 0。部分懒加载页面已追加等待检查，不能把导航成功等同每个业务操作完成。
- QuantBot 一次真实 `execute_shell_command` 返回 Linux、QuantDB/backend 目录存在，2.73 秒结束。证据在云端 `/data/quantmind-migration-smoke-20260908-verified/`（qwenpaw 容器内）。未继续旧研究会话。
- 训练/回测运行时：隔离容器 `network=none`、只读代码、无正式数据挂载，LightGBM 27 行合成数据训练与模型保存/重载一致；Qlib/CnExchange 10 日回测、2 笔成交，现金/资产核对误差为 0。可复跑 `scripts/test_migration_runtime.py`；这是合成运行时验收，不是所有市场/模型的训练业务全覆盖。
- Mac 浏览器断网模拟：请求失败、登录状态和后端配置保留；恢复网络后模型 API 返回 200。测试未切断整台 Mac 的 Wi-Fi，也未重启整台云服务器。
- Mac 旧 PostgreSQL、行情网关、RSSHub 也已停止，9 个本地旧容器均为 `restart=no`。`deploy/compose.mac-client.yml` 安装为仅 Mac 使用的忽略同步 override，裸 Compose 默认不选择旧服务。明确指定服务或绕过覆盖层仍可突破，开发规范禁止这样操作。
- 17 项部署边界回归、4 项前端服务选择回归、8 项因子读取测试通过；后者同时在云端隔离容器和 Mac 独立依赖环境执行。TypeScript 类型检查与前端构建通过。保留现有构建警告，不宣称全仓测试全部通过。QuantBot 嵌入页面的图片路径也统一走静态代理，避免根路径图标 404。
- Syncthing 状态之外增加全源码/共享配置内容哈希核对（含 Git 忽略的共享密钥，输出不含密钥内容）、冲突拒绝和连接状态检查。Git HEAD/分支独立核对。新增规则也写入 `AGENTS.md` 和 `CLAUDE.md`，避免不同编码助手遵循旧本地主库命令。
- 新增 Mac 全栈开发沙盒：`scripts/local-dev.sh init` 从已校验快照建立 APFS 写时复制副本并恢复独立数据库/Redis/QwenPaw 卷；`start core|full` 使用本机 CPU/内存，`stop` 恢复 8000 云端隧道。沙盒、旧迁移卷和云端权威卷三者隔离，沙盒数据不经 Syncthing，也没有双主合并。

公网 3080 当前仍为 HTTP、默认管理员凭据尚未更换。最终审查还发现 QuantBot 通用 API 代理缺少独立鉴权，而其上游具备命令执行能力；前端登录不是该代理的访问控制，仅改管理员密码不足以修复。公网安全验收未通过，已请用户选择先限制 SSH-only，或补齐入口鉴权与 HTTPS；未获选择前保留用户原来要求的端口配置。未执行真实交易、长期研究或全部第三方数据源更新。

## 已确认的目标

- Mac 与 lzy-vm 双向同步完整源码工作树、未提交代码、文档、Skills 和共享配置，包含 `.env.local`、`config/runtime.env`。
- Mac 会断网：离线修改代码保留在本机，重新连接后同步；同一文件两端同时编辑需要处理冲突，不承诺自动语义合并。
- 数据以 lzy-vm 为唯一权威源。Mac 离线研究基于最后已校验快照，本地新结果在联网登记成功前不是权威结果。
- 数据库、任务队列和调度器不得出现两个并发主节点。机器依赖分别安装；Git 元数据独立维护。

## 已实施并验证

- 云端 SSD：`/dev/vdb`，磁盘 ID `disk-joxd1ee9`，容量 500 GiB，ext4。
- UUID：`3c46a144-f3a3-4250-95ee-e85fb5d8e88a`。
- 挂载点：`/root/data/disk`；迁移、备份和首份快照完成后，`df` 显示可用约 327 GiB。
- 修正 `/etc/fstab` 中相对挂载路径为绝对路径；原文件保留于 `/etc/fstab.quantmind-ssd-backup-20260907`。`findmnt --verify` 已无错误；未以重启验证。
- 项目：`/root/data/disk/quantmind/project`，入口软链接 `/root/code/QuantMind`。
- 独立目录：`/root/data/disk/quantmind/volumes`、`backups`、`staging`、`snapshots`，顶层目录权限 0700。
- 复用两端现有 Syncthing 服务，新建 `quantmind-code`，类型 `sendreceive`，启用文件监听和 10 个历史版本。原有 Guanlan 文件夹状态未改动。
- `.stignore` 通过 `#include .sync-code-ignore` 加载共享规则；根 `.stignore` 已分别安装到两端。
- 验证 Mac 到云端、云端到 Mac 的临时探针同步；验证 `.env.local`、`config/runtime.env`、关键训练代码和 SQL 升级脚本的两端 SHA-256 相同。密钥文件在云端保持 0600。
- 云端 Git 从本机独立初始化，保留当前浅克隆边界、已有本地分支和当前未提交修改。初始 HEAD 为 `3f3c2f7c77b941cb213097bdb81dc926a60f3d9b`，分支 `codex/dark-mode`；Git 对象连通性检查通过。

## 代码同步范围

同步源码与共享配置；排除 `.git`、依赖、缓存、日志、数据目录和研究产物。保留 `data/upgrade_v*.sql`、`data/stocks` 及 `db/sql` 等源码资源。`.stversions` 已被 Git 忽略，避免历史密钥进入 Git 提交。

Syncthing 的历史版本保存在接收端，不等于应用一致性备份。两端 Git 已在保留工作树内容的前提下对齐到 `master`；后续提交、分支及合并仍需通过 Git 管理，不由 Syncthing 同步。运行中的服务也不会仅因文件同步而自动切换代码版本。

## 仓库是同步和部署配置的来源

- `deploy/dual-node.env`：SSH 别名、SSD UUID、项目真实路径、Syncthing 设备和端口。
- `.sync-code-ignore` / `.stignore`：代码与数据的互斥边界。`.env.local`、`config/runtime.env` 会经加密的 Syncthing 同步，但不提交 Git。
- `scripts/dual_node_sync.py mac|cloud [--apply]`：对照仓库检查/对齐本项目的实际 Syncthing 配置；不会修改其他共享文件夹或新增共享设备。
- `deploy/compose.cloud.yml`：云端资源上限、仅 3080 对公网、SSD 持久化卷、禁用实盘及暂停其他容器。
- `scripts/dual-node.sh`：可续传预复制、镜像传输、前端发布、云端 Compose 和 SSH 访问。
- `scripts/dual-node-cutover.sh` / `dual-node-restore.sh`：停写、备份、最终增量、逐文件校验、数据库恢复及唯一主节点切换。
- `scripts/dual_node_inventory.py` / `deploy/table-counts.sql`：SHA-256 文件清单与全部 PostgreSQL 表的精确行数。
- `scripts/dual_node_snapshot.py`：云端一致性快照及 Mac 校验下载；不覆盖本机已有研究目录，不回灌数据库。
- `scripts/dual_node_deploy.py`：串联传输、校验、切换、连接检查和首份离线快照；运行状态写入 `logs/dual-node-deploy.json`，同一时间只允许一个编排进程。
- `deploy/com.quantmind.cloud-tunnel.plist`：切换后才安装的 Mac 自动重连 SSH 隧道，保留本地开发入口访问云端的能力。
- `deploy/syncthing-ssd.conf`：系统启动时等待 SSD 挂载，已安装到云端 systemd drop-in。
- `deploy/quantmind-stack.service`：云端完整服务的开机入口，等待 SSD 和 Docker，并要求权威源标记存在；已安装、启用并验证 active，未做整机重启测试。
- `scripts/check_cloud_health.py`：检查 8000–8003 四个内部服务，避免仅 API 存活掩盖子服务失败；用 Python `-S` 跳过全局 AI 库初始化，探针不依赖外网。
- `python3 scripts/test_dual_node.py`：端口、共享规则、卷路径、训练安全开关的回归检查。

两端配置核对命令（Mac 项目根目录）：

```bash
python3 scripts/dual_node_sync.py mac
ssh lzy-vm 'sudo -n python3 /root/code/QuantMind/scripts/dual_node_sync.py cloud'
bash scripts/dual-node.sh status
```

云端原有服务已占用较多内存，训练编排原来的“至少 20 GiB、约宿主 80%”规则不适合共用服务器。云端 API 派生的训练容器明确限制为 4 GiB、模型线程数 2、IC worker 1；大型训练可能因自身资源超限失败，应单独规划训练节点，不能以暂停其他项目来换内存。手工 Docker 作业和其他研究工具也需要自行遵守共享机器预算，这不是覆盖所有任意 root 命令的全局资源隔离。

修改规则后，先核对再执行 `--apply`。如 `.stignore` 被外部工具改动，脚本会报错而非忽略。Git 元数据仍不交给 Syncthing；分支/提交需要单独通过 Git 传递，不能把 `.git` 加回同步。

长时间运行的 shell 脚本启动时会捕获自身内容，避免运行过程中被 Syncthing/编辑器更新后继续读到错位的新文件。这个场景有实际启动子进程并改写脚本的回归测试，不只是静态检查。

## 数据迁移与云端上线进度

2026-09-08 09:37 CST 已写入云端 `AUTHORITY`，lzy-vm 成为唯一数据主节点。Mac 原写入容器保持停止且自动重启策略为 `no`，不要直接重新启动旧的完整本地 Compose 栈。

- 351,338 个运行数据文件、68,057,092,833 字节，两端 SHA-256 清单一致；恢复前再次对 Mac 全量校验，避免其他研究工具在停写期间改变输入。
- PostgreSQL 事务恢复完成，114 张表的精确行数全部一致；其中 `public.stock_daily_latest` 为 10,803,423 行。冷卷归档校验全部通过。
- 恢复点：云端 `backups/migration-20260907T223006Z`，Mac `logs/dual-node-20260907T223006Z/`。最初 SSH 中断后复用恢复点续传，没有重新启动本地主节点。
- 首份快照 `snapshot-20260908T013700467725Z` 在任何云端应用写入者启动前创建；已下载到 Mac `logs/cloud-snapshots/` 并通过完整校验，双方 `latest` 指向此快照。
- 首次快照下载约 68GB 文件数据全部复用 Mac 原有内容，没有传输文件主体；数据库与归档约 3.08GB 中，约 3.00GB 使用现有备份块，新增字面数据约 15.52MB。网络仍有文件清单和协议开销。
- 开发前刷新快照 `snapshot-20260908T134413970428Z` 已在云端和 Mac 双端校验，包含 351,346 个运行数据文件、68,061,617,857 字节。云端创建从 21:44:13 到 22:16:55 CST，应用停写约 30 分钟，随后 10 个容器全部恢复且 OOM 计数为 0。
- 第二份快照复用不可变文件后，SSD 约使用 144 GiB、可用 324 GiB。Mac 拉取数据库与归档约 3.08GB 时实际接收约 12.7MB；运行数据逻辑大小约 68GB，只传 45 个常规文件、实际接收约 20.0MB。两端 `latest` 均已原子切到新 ID，旧本地研究目录未覆盖。
- 公网 3080 与 SSH 隧道 18080 首页均 HTTP 200；登录页已实际渲染，公开注册被拒绝（403）。没有使用未知密码登录，也未执行完整训练、交易或离线结果回灌验收。
- QwenPaw 47/47 技能启用。迁移用整卷恢复保留注册状态，未手工复制技能。

上线检查曾发现主容器 3GiB 上限引发子服务 OOM。已提高为 6GiB，禁用主容器内置 Celery，保留独立 worker，并将健康检查扩大到四个内部服务。新容器检查时 cgroup OOM 计数为 0。共享服务器内存仍紧张，不代表大型并发训练已获得足够容量。

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

镜像和前端准备好后，也可让编排脚本完成后续全部步骤：`caffeinate -i python3 scripts/dual_node_deploy.py`。已有预复制正在运行时用 `--wait-for <PID>` 接续，不重复启动传输。编排重试预复制中的暂时网络错误，并在研究任务忙时等待；停写后的其他错误会停止流程，不会盲目重启 Mac 主节点。云端恢复与快照创建由一次性 systemd 服务托管，SSH 观察连接中断不会杀掉恢复/解冻进程；可用 `journalctl -u quantmind-cutover` 或 `journalctl -u quantmind-snapshot-create` 查看。

切换脚本只停止 QuantMind 的写入服务，发现独立研究容器或活动 Celery 任务时拒绝切换。PostgreSQL 用事务一致性 dump 跨 CPU 架构迁移；Redis、Huntly、QwenPaw 停写后迁移。QwenPaw 整卷恢复包含其注册清单，后续技能更新仍只走 `quantbot_init.sh`，不能单独复制技能目录。

初次预复制不删文件。最终停写增量只在明确的数据子目录内对齐删除，被替换/删除的旧文件保留在本次迁移备份的 `displaced/`，不是不可恢复清除。所有文件清单一致、数据库 dump/卷归档校验一致、114 张表的行数一致后才启动云端写入者。目标数据库非空时拒绝覆盖。

备份位置：Mac `logs/dual-node-<UTC>/`；云端 SSD `backups/migration-<UTC>/`。切换失败后写入服务保持停止，先查看日志和云端 `AUTHORITY`，不得在云端已成为主节点后直接重启 Mac 的旧主库服务。

停写后网络中断的恢复入口：`bash scripts/dual-node-cutover.sh --resume logs/dual-node-<UTC>`。仅接受仓库日志目录内完整的既有备份；要求云端尚未接管、本机六个写入容器全部停止，并核对 PostgreSQL 表行数未变化。重用备份，续传最终增量后重新执行完整校验，不重新启动 Mac 主节点。SSH/rsync 启用连接超时与保活；恢复步骤的其他错误仍停止供人工检查。

首次恢复在数据库行数验证通过后、任何应用写入者启动前创建离线基线快照。后续编排复用已有的已完成快照进行校验下载，不为同一次切换再次创建全量基线。

切换会把 Mac 写入容器的自动重启策略改为 `no`，防止重启 Docker Desktop 时复活第二个主节点。Syncthing 不受影响，断网重连后继续同步源码；`preseed` 在切换后会明确拒绝向权威数据目录回灌。

## 两端访问及离线边界

联网时可直接访问云端 3080；也可运行 `bash scripts/dual-node.sh connect`，通过加密 SSH 隧道访问 `http://127.0.0.1:18080`。两种入口指向同一服务、同一数据库。公网当前是 HTTP，没有部署域名/TLS；涉及密码和研究数据时优先使用 SSH 隧道。

云端 Nginx 拒绝公开注册接口，仅使用迁移来的现有账号；数据库、Redis、QwenPaw 和内部 API 不直接对公网发布。该策略由 `deploy/nginx-registration.conf` 管理，不改变本地开发的默认注册行为。

编排在云端 API 验证通过后执行 `install-tunnel`，已安装并启动 `com.quantmind.cloud-tunnel` LaunchAgent。它把 Mac `127.0.0.1:8000` 和 `18080` 接到云端 3080；原有本地 Vite 页面仍通过 8000 访问同一份云端数据。已定向终止本项目隧道进程，验证 launchd 自动拉起新进程，18080 恢复 HTTP 200；未对整台 Mac 做断网测试。若端口被无关服务占用则拒绝安装，不会抢占端口。

Mac 断网不影响云端服务。断网时本机现有数据是截至切换时的离线基线，代码编辑和冻结数据研究可以继续，但云端新数据不可能实时出现在离线 Mac。

权威源切换完成后，在无研究任务的时间主动创建/拉取新快照：

```bash
ssh lzy-vm 'sudo -n systemd-run --unit=quantmind-snapshot-create --wait --collect --property=RequiresMountsFor=/root/data/disk /usr/bin/python3 /root/code/QuantMind/scripts/dual_node_snapshot.py create'
python3 scripts/dual_node_snapshot.py pull
```

创建快照会先做不停服预复制，然后停止本项目写入容器，完成最终文件校验、PostgreSQL dump 和冷卷归档，最后恢复原来运行的容器。本次 68 GB、35 万文件的完整校验与归档造成约 30 分钟停写，应预留维护窗口，不能当作秒级在线备份。未完成尝试复用 `.building` 暂存目录，不会每次失败都另造一份全量副本；快照仅在全部校验通过后发布。Mac 下载到 `logs/cloud-snapshots/<snapshot-id>/`，校验通过才更新 `latest`。首次下载用 `--copy-dest` 校验并复制 Mac 已有的相同文件，不重复从网络下载，也不会与活跃源共享硬链接；后续不可变快照之间使用 `--link-dest`。不覆盖本机原有 `data/`、`results/` 或数据库。研究时使用快照的明确 ID，不能在研究期间切换输入版本。

部署回归测试 14 项通过，首次云端全量快照、Mac 下载和逐文件校验均已完成；尚未安装定时刷新。离线研究产物应单独保留，不能直接回灌数据库；自动结果登记和一键离线完整应用启动尚未实现。离线可编辑代码、读取快照开展研究，但原在线界面依赖云端 API。不能把这一状态描述成自动双向数据库同步、完全离线可用的完整应用，或声称离线时仍与云端实时一致。

代码同步不等于运行中的进程自动更新。前端改动用 `web-publish` 构建并发布，旧静态文件保留于云端 `staging/web-*.previous`；后端改动完成核对后，通过仓库里的 `cloud-compose restart` 重启对应服务。
