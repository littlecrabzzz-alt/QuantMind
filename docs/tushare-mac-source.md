# Mac 全量归档、云端研究子集

用户于 2026-09-16 确认以价格成本为优先：Mac 保存全量数据，以后迁移 NAS；云服务器从 Mac 取研究数据，不长期保留全量归档。业务数据库和 QuantDB 的既有日常采集链路不在此次 Tushare 迁移中改写。

## 供数入口

`scripts/tushare_research_cache.py serve --root <Mac归档目录>` 从已校验的固定 release 提取研究 API 的 Parquet 和其引用的 observation，独立校验后生成带 `source_release_id` 的子集 release。原始对象、附件、SQLite、配置与密钥不经此 HTTP 入口提供。服务仅监听 127.0.0.1，通过 SSH 反向端口转发供云服务器访问；不开放公网端口。

云服务器执行 `pull --root <独立研究缓存> --source http://127.0.0.1:18765`，核对固定版本与文件哈希后才更新 CURRENT。默认缓存预算 100 GiB、磁盘空闲保留 100 GiB；超限和 Mac 不在线时保留旧版并失败退出。初版不自动删除旧缓存文件，避免清除运行中研究输入；预算用尽必须显式安排已结束版本的回收。研究子集不声称历史完整，现有 reader 可按子集 release 查询，无 Tushare 回退。

默认提供 daily、index_daily、fund_daily、adj_factor、daily_basic、index_weight、ci_daily、sw_daily、stock_basic、index_basic、fund_basic、trade_cal 中源 release 已有的数据。接口集合可显式指定；这不是所有研究需求的永久白名单。

## 迁移门槛与容量

1. Mac 归档位于 `~/Library/Application Support/QuantMind/tushare`，与 `.local-dev` 研究沙盒分开。当前镜像成功只证明一个固定 release 可用，不证明云端所有未发布数据与采集状态已接收。
2. 在切换唯一采集者前，必须保存云端一致的采集/文档/归档 SQLite 检查点、权限配置及全部已采集文件，逐项校验。不得复制正在写入的 SQLite 文件来冒充迁移完成。
3. 切换后全量采集在归档节点进行；Mac 休眠时暂停，云端使用已缓存研究版本。NAS 迁移同样按校验、唯一写入者、原子切换流程执行。
4. Mac 至少预留 300 GiB；低于 500 GiB 时准备 NAS 迁移，达到保留线停止新采集/下载而非删除唯一归档。此处阈值是目标策略，采集迁移完成前不得声称已生效。
5. 云端原有 Tushare 全量目录只在全量迁移证据完成后回收；新子集缓存和旧全量目录在过渡期会暂时并存。当前代码没有自动删除云端全量数据的入口。

### 完整迁移验收入口

`scripts/tushare_archive_migrate.py --root <归档目录>` 进行可恢复预复制；
只靠大小/时间判断哪些文件需要重传，最终完整性由独立 SHA-256 验收保证。
预复制不传活跃 SQLite，不切换 CURRENT，不授予采集权限。

仅在关闭 Tushare 新任务准入、确认在途任务自然排空后，云端执行
`--action checkpoint`。它要求 ENABLED 不存在，并独占 pipeline/documents/archive
三把锁，使用 SQLite backup 创建一致检查点，对所有历史及未发布文件生成
`.migration/checkpoint-*/inventory.jsonl` 和 COMPLETE.json。锁繁忙直接失败，
不会停止 QuantDB 或其他服务。窗口内须保持 Tushare 准入关闭。

继续传输冻结归档，将清单中 checkpoint_path 对应的数据库副本安装到目标 path，
然后 Mac 执行 `--action verify --checkpoint <已传输的检查点目录>`。
校验包含文件路径、大小、SHA-256 和清单总数，缺失或损坏即失败；此命令只证明
文件迁移，不生成 ARCHIVE_AUTHORITY，也不宣称供应商历史全量完成。
最后还需独立核验云端停写、Mac 唯一采集者、权限/日配额连续性及真实采集结果。

### 本地采集运行环境

在 Mac 执行 `python scripts/install_tushare_archive.py`，复用持久客户端 Python，
安装完整 Tushare 共享模块、目录配置和文档解析器（与当前云端版本相同）。
默认仅准备运行环境，不启动采集。Token 单独放入运行目录的
`config/archive.env`，权限 0600，只保存 TUSHARE_TOKEN，不纳入源码或数据同步。

完成完整归档迁移、云端停写与所有权验收后，才执行
`python scripts/install_tushare_archive.py --activate --root <完整归档目录>`。
激活前检查已部署代码的 authority、节点标记及密钥文件权限，安装
`com.quantmind.tushare-archive` LaunchAgent。已有采集进程时拒绝覆盖运行代码，
升级须先自然结束当前采集周期。300 GiB 停写线和 500 GiB NAS 提醒由 worker 执行。

云端定时缓存使用 `deploy/tushare-research-cache.service` 和对应 `.timer`，
安装到 `/etc/systemd/system/` 后启用 timer。部署前等待当前临时拉取 unit 结束，
避免重复扫描。定时器在上次结束 15 分钟后再拉，离线失败保留 CURRENT。
传输最多同时下载 8 个对象，`cache-transfer-status.json` 每 100 个完成文件更新；
`cache-status.json` 仅在全部文件验证并原子切换 CURRENT 后更新。

应用接口读取切换由部署变量 `QM_TUSHARE_READ_STORE=research-cache` 控制，
仅允许 `archive`（过渡期默认）或 `research-cache` 两个固定目录，客户端不能指定路径。
切换前须验收所需研究数据及固定版本，之后在应用服务可重启窗口加载该变量；
不能仅因首次小子集传输成功，就宣称整个应用已经使用新缓存。
云端 Compose 显式传入该变量，默认仍为 `archive`。完成验收后在云端部署 `.env.local`
设置 `QM_TUSHARE_READ_STORE=research-cache`，通过
`bash scripts/dual-node.sh cloud-compose up -d --no-deps quantmind` 重建应用容器以加载变量；
仅 `restart` 不会更新容器环境。Mac 沙盒目前仍读取自己的快照目录，完整归档迁移
本身不会自动改写沙盒容器挂载，应用读目录需另行核验。

Mac 应用的 Tushare HTTP 读取入口支持 `.env.local` 中的 `QM_LOCAL_TUSHARE_ROOT`，
默认是原沙盒 `data/tushare`，以只读方式挂载到应用容器的 `/data/tushare`。
完整迁移及固定版本验收后，将其设置为 Mac 归档绝对路径；以后可设置为 NAS 挂载路径。
在本地任务空闲的窗口，通过 `bash scripts/local-dev.sh recreate-backend` 仅重建 API 容器，
随后核对 Docker 实际挂载的源目录、只读标志和指定 release 的真实查询。仅重启后端
不会更换挂载。此变量只改变应用读入口，不改变独立采集进程、业务库及其他沙盒数据；
独立研究作业仍按其冻结输入契约读取数据。
该入口保留本地角色检查及操作锁，不构建或拉取镜像，不重启数据库和研究 worker。
切换前核对当前容器与本地 `quantmind-oss:latest` 镜像一致，避免混入其他镜像更新。
切换后的可重复只读检查（NAS 时替换 expected）：

```python
import json, subprocess
from pathlib import Path
expected = str(Path.home() / "Library/Application Support/QuantMind/tushare")
container = json.loads(subprocess.check_output(["docker", "inspect", "quantmind-dev"]))[0]
assert any(m["Destination"] == "/data/tushare" and m["Source"] == expected
           and not m["RW"] for m in container["Mounts"])
```

最终迁移的 CURRENT 随冻结检查点暂存；验收时可加 `--staged-current` 检查
检查点中的新指针，保持本地当前读版本不变。所有文件校验和唯一写入者交接
通过后，才原子发布这个指针。不要先覆盖 CURRENT 再尝试完整性校验。

数据库安装使用 `--action install-checkpoint --checkpoint <本地检查点目录>`：
验证清单和每份数据库哈希，取得本地写锁后原子安装。重复执行复用相同文件；
发现已有不同数据库、SQLite WAL/SHM/journal 或已启用采集则拒绝覆盖。该步骤不发布
CURRENT，也不授予所有权；之后仍必须运行完整归档校验和唯一写入者交接。

交接完成后云端写入 `ARCHIVE_RELOCATED.json` 作为持久停写标记；云端 authority
检查会拒绝继续采集，即使以后误恢复 ENABLED 也不能重新成为采集节点。
此标记只能在完整迁移验收及接管交接时生成，目前预复制阶段不创建。

本地完整补传和数据库安装结束后，执行
`--action finalize --checkpoint <本地完整检查点>`：在迁移锁下重新逐文件校验，
经 SSH 调用云端 `seal-source`，核对云端仍暂停、CURRENT未变且三把写锁可取得。
云端记录接管节点和清单摘要；本地验证返回的摘要和节点身份匹配，才发布暂存
CURRENT、ARCHIVE_AUTHORITY 和 ENABLED。任何匹配失败都不会启用本地采集。
随后使用本地安装程序 `--activate` 启动唯一采集 worker，实际采集验收另行完成。
这套接管不删除任何源数据，也不能替代 Tushare 历史队列完成度验收。

冻结检查点完成后可执行 `--action sync-frozen --checkpoint <检查点目录名>`。
入口通过 SSH 确认源仍暂停且 COMPLETE 存在，补传最终不可变文件，再拉检查点
和采集配置；随后才执行 install-checkpoint/finalize。该步骤保留原 CURRENT，
不复制活跃 SQLite，不启用采集；中断后可复用 rsync 已完成的文件继续。

接管写入采用 pending 所有权标记：先标记 migration_verified=false，再写 ENABLED，
最后提交已验证所有权。若中断发生在其中，authority 会继续拒绝采集；对同一节点、
同一检查点重跑 finalize 会重新验证并继续。已经完成的所有权不会被再次覆盖。

云端交接完成后还需在独立服务窗口重新加载 celery-beat，使调度读取
ARCHIVE_RELOCATED 标记并移除 Tushare continuation；市场同步和市场快照调度
保持原样。确认云端Tushare在途任务为空后，停止两个专用Tushare worker，
不要停止QuantDB的market_sync worker或整个Compose栈。
两个旧 Tushare worker 归入 `legacy-tushare-acquisition` Compose profile，常规整栈启动
不再自动拉起它们；`ARCHIVE_RELOCATED` 仍负责拒绝写入，profile 本身不是所有权控制。

本地运行环境同时安装 `httpx[socks]`，并在安装验收时构造HTTP客户端。
macOS系统代理可能提供SOCKS条目，即使HTTPS请求走HTTP代理，HTTPX初始化也需要
SOCKS依赖。仅测试import httpx不足以证明采集能发出请求；本次已用原私有凭据
在Mac真实读取两日trade_cal，HTTP200/业务码0/两行，未启动全量采集。

归档补传使用 rsync -H 保留源硬链接：archives与releases中同一份不可变清单只占
一份文件空间。最终补传也会把先前分开复制的别名恢复为硬链接；不删除任何历史
版本或字段，最终仍按照每条清单引用校验哈希。已用实际rsync本地夹具验证恢复行为。

本地持续采集实测发现，东方财富板块的饱和分区恢复会反复扫描全部发现记录。
现在只读取其全部三个来源 `dc_index`、`dc_member`、`dc_daily` 的现存结果和历史尝试，
继续合并父响应中的标识，保留未知全集及分区闭包检查；剩余批次预算可继续发请求。
同一冻结数据库的只读对比得到完全相同的 1,050 个标识及集合哈希，发现耗时由
93.47 秒降至 7.92 秒。该测量只证明此发现阶段的提速，不代表持续 API 吞吐已达上限。

迁移后的云端空间回收复用 `scripts/tushare_archive_migrate.py`，分两步执行：
Mac 使用 `--action verify-preserved --root <完整归档> --checkpoint <其冻结检查点>`，
重新逐文件哈希校验原始对象、文档、附件、提取文本、Parquet、观察记录、模式及历史清单，
成功才写检查点内的 `PRESERVED.json`。此时采集可继续追加，不修改本地存量文件。
将该验收文件送到云端对应检查点，再使用 `--action prune-relocated --root <旧归档>
--checkpoint <云端检查点> --receipt <PRESERVED.json>` 做只读预检；增加 `--apply` 才删除。
前置条件是应用读取已切换且研究固定输入已核对。入口校验两端交接身份、清单及总量，
持有三把旧采集写锁，确认源未恢复采集且 CURRENT 不变，每次删除前核对源文件哈希。
不匹配立即停止并保留剩余文件；中断后重跑跳过已不存在的文件。清单之外的新文件不删除。
源数据库、检查点、停写标记、其他业务数据、独立研究缓存和完整快照都不属于此删除范围。
`logical_bytes` 包含硬链接别名，不能当成实际磁盘回收量，回收后另查文件系统可用空间。

原生归档循环让接口采集与文档处理在同一轮并行，复用原云端两个 worker 已使用的
独立写锁及数据库连接。文档仍限定每轮 100 个处理阶段、90 秒和至多两个下载者，
不提高供应商接口频次。每轮等待两项任务全部结束后再进入下一轮；升级时仍须先
暂停 ENABLED 并等待两类写锁排空。状态记录的 `started_at` 表示开始时间，
`updated_at` 为完成时间，`elapsed_seconds` 为整轮耗时；文档失败不会报告整轮成功。

发现标识时，`jobs_discovery_api` 仅索引已有结果的任务，`attempts_discovery_api`
索引历史尝试的接口名，避免每次分区展开扫描数百万待采任务。索引在事务中补齐，
失败回滚；不改 v6 表结构、行内容、历史尝试或批处理工具的版本约束。
冻结库的隔离副本验证了索引前后股票/板块查询的 94/9,045 条结果及哈希一致；
这只验证发现查询，不代表整个采集循环或全部历史已经完成。
