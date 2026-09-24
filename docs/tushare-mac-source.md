# Mac 全量归档、云端研究子集

用户于 2026-09-16 确认以价格成本为优先：Mac 保存全量数据，以后迁移 NAS；云服务器从 Mac 取研究数据，不长期保留全量归档。业务数据库和 QuantDB 的既有日常采集链路不在此次 Tushare 迁移中改写。

## 供数入口

`scripts/tushare_research_cache.py serve --root <Mac归档目录>` 从已校验的固定 release 提取研究 API 的 Parquet 和其引用的 observation，独立校验后生成带 `source_release_id` 的子集 release。原始对象、附件、SQLite、配置与密钥不经此 HTTP 入口提供。服务仅监听 127.0.0.1，通过 SSH 反向端口转发供云服务器访问；不开放公网端口。

云服务器执行 `pull --root <独立研究缓存> --source http://127.0.0.1:18765`，核对固定版本与文件哈希后才更新 CURRENT。默认缓存预算 100 GiB、磁盘空闲保留 100 GiB；超限和 Mac 不在线时保留旧版并失败退出。初版不自动删除旧缓存文件，避免清除运行中研究输入；预算用尽必须显式安排已结束版本的回收。研究子集不声称历史完整，现有 reader 可按子集 release 查询，无 Tushare 回退。

当新全量发布的子集准备耗时较长时，供数入口立即返回上一份已经校验的研究子集，同时后台准备新版。云端 `cache-status.json` 的 `source_release_id` 表示实际提供的全量源版本，`latest_source_release_id` 表示 Mac 请求时的最新全量版本；`source_lagged=true` 必须视为数据新鲜度缺口，不能把本轮缓存任务成功解释为追平。新版准备完成后，下轮拉取再校验并切换；准备失败保留旧版并记录错误，不回退到 Tushare Pro 直拉。

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
`archive_worker_cycle_seconds` 默认 120 秒，合法范围 105 至 3600 秒；它只缩短有界
采集轮次之间的空等时间，不改变账户、接口或每日配额门。缩短周期前后都必须以真实
生产轮次核对请求数、限频响应、失败阶段、文档并行任务和磁盘余量。

本地全量归档的示例发布周期为 21600 秒，规划周期仍为 900 秒。发布固定版本会扫描
全部持久化元数据并生成不可变 manifest；它不负责提交单次 API 响应，原始对象、
observation、Parquet 和 attempt 在采集事务中已经落盘。随着全量库增长，每小时重建
固定版本会显著挤占采集时间，因此正常全量同步采用六小时发布一次，需要立即冻结验收
输入时仍可显式调用发布入口。改变发布周期不改变 Tushare 限频、规划周期、磁盘保留线
或唯一写入者边界；生产调整必须保留配置前后哈希并观察至少一个真实采集周期。

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
独立写锁及数据库连接。文档配置硬上限为每轮 1,000 个处理阶段、100 秒和至多四个
下载者；生产可以在该范围内调整，不提高 Tushare 接口频次。每轮等待两项任务全部
结束后再进入下一轮；升级时仍须先
暂停 ENABLED 并等待两类写锁排空。状态记录的 `started_at` 表示开始时间，
`updated_at` 为完成时间，`elapsed_seconds` 为整轮耗时；文档失败不会报告整轮成功。

文档来源的临时终态不会永久遗漏。默认每个终态至少冷却 24 小时，每轮最多恢复 16
个任务，并在尾部空格 URL、扩大后的大小上限、来源挑战、内容重检和网络失败之间
轮转。调度只改回 `retry`，保留原始响应、下载次数和全部 attempt；重复失败重新开始
冷却。下载大小默认仍为 25 MiB，配置只能提高到 256 MiB，隔离下载子进程继续受 20
秒任务期限约束。以 `%PDF-` 开头但缺少 `%%EOF` 的完整正文保存为 PDF 并进入受限
解析器，状态为 `pdf_prefix_only`；它不等于结构有效，解析失败仍作为显式缺口保留。
来源脚本只保存为不可变证据，不执行、不生成 Cookie，也不引入浏览器会话。

发现标识时，`jobs_discovery_api` 仅索引已有结果的任务，`attempts_discovery_api`
索引历史尝试的接口名，避免每次分区展开扫描数百万待采任务。索引在事务中补齐，
失败回滚；不改 v6 表结构、行内容、历史尝试或批处理工具的版本约束。
冻结库的隔离副本验证了索引前后股票/板块查询的 94/9,045 条结果及哈希一致；
这只验证发现查询，不代表整个采集循环或全部历史已经完成。

全量规划发现使用 `identifier_discovery_cache` 保存已处理 attempt 的最高 rowid、
完整标识集合及所有引用对象的 stat 指纹。缓存命中前仍逐个确认旧对象存在且未变化，
并确认旧 attempt 未被删除；之后只解析新增 attempt。任何旧记录删除、对象缺失或
对象指纹变化都会拒绝缓存或重新完整发现。缓存是 v6 数据库内的可重建派生表，
不改变 `user_version`、原始响应、历史尝试、规划游标或权限结论。
对象复核以最多 8 个固定分片并发执行，仍覆盖全部缓存对象并逐项比较设备、inode、
大小、mtime 和 ctime；删除或指纹变化的失败语义不变，仅缩短本地文件 stat 等待。
生产库只读备份实测：首次处理 120,257 条结果、读取 115,534 个对象正文约 93.03 秒；
第二轮结果 SHA-256 完全相同，读取正文 0 个，约 5.24 秒。该缓存仅用于周期规划；
饱和分区的限定来源发现仍走原验证路径。

原生 worker 在发布到期时先让 `tick` 取得文档锁并完成固定版本发布，再启动当轮
文档处理；非发布轮仍由回调在采集前启动文档线程并保持并行。这样不会因文档线程
每轮先持锁而让发布永久延后、采集连续返回 0 请求。

`planning_only` 是持久化扩展全量任务队列的周期，不是 dry-run；该周期不访问
Tushare，成功后由原生 worker 最少等待 5 秒便进入下一次真实采集。
原生 Mac 归档 worker 可启用 `archive_worker_acquire_after_planning`；规划成功且
当前 worker 周期仍剩至少 1 秒安全预算时，它重新进入原 `tick` 并只用
剩余预算执行真实采集。第一步仍是 0 上游请求的独立持久规划事务；
发布优先级、规划断点、请求频控与失败恢复语义不变。预算不足时保持
`planning_only` 并按原 5 秒最小延迟进入下轮。

`fund_nav_recent_date_pagination` 默认关闭。启用后，近期七天的基金净值按精确
`nav_date` 生成根任务，并使用已在 Mac 权威归档上实测通过的 1,000 行
`limit/offset` 分页链；历史范围仍按每只基金的 `ts_code + start_date/end_date`
补采。分页只对含 `nav_date` 的新任务生效，既有逐基金任务、结果和尝试均保留并
正常排空，不以一次近期分页探针替代历史完整性。脱敏证据见
`docs/tushare-fund-nav-pagination-live-evidence.json`；官方参数表未列出分页参数，
因此该能力必须保留为可回退的灰度开关。

`fina_mainbz_vip` 与逐股票 `fina_mainbz` 的历史任务可能暂时并存。每次规划后只对 10,000 行合同的
VIP 分页链做覆盖压缩：同一年、同一 P/D/I 类型的四个季度必须均以连续 offset
分页到不足 10,000 行的终页，才将同字段的逐股票完整年度待采任务标记为
`superseded`。空根、缺页、异常页、部分年度、近期周更、已有结果和历史尝试均保留。
规划指纹只排除 `document_*`、`enable_documents` 和旧内联文档预算；这些键只控制
独立文档队列，改变它们不会再消耗一个结构化采集周期。目录、范围、接口、权限及
其他采集配置仍参与指纹，A→B→A 仍逐次规划。旧整配置指纹只有在与当前完整配置
精确匹配时才原子迁移并保留原成功时间，否则继续按配置变化重新规划。

规划周期还会低频复查已确认的权限缺口。默认只有 `checked_at` 超过 7 天的
`permission_denied` 范围符合条件，每轮最多恢复 4 个范围中的各一条代表任务；复查
任务仍经过共享账户/API 限速及每日总量约束。调度只把代表任务改回 `pending`，保留
原始结果、重试次数和 attempt 记录，并用持久化检查点避免同一规划周期重复调度。
若真实响应继续拒绝，权限证据时间会刷新，其余任务保持 `permission_blocked`；只有
真实成功才把同一 `api_name + src` 的任务精确恢复为 `pending`。不同来源、不同接口
以及没有已保存任务的权限范围不会被推断为可用。

同一低频复查还覆盖供应商明确返回业务码 40101“请指定正确的接口名”的
`api_unavailable` 范围。原始响应、观察记录和全部 attempt 保留；新规划任务直接进入
`blocked`，避免每轮重复请求。达到复查间隔后每个范围只恢复一条代表任务，仍受
`permission_reprobe_max_scopes`、共享账户/API 限速和每日总量限制；真实成功才恢复同一
`api_name + src` 中结果为空或 `api_error` 的阻塞任务。其他 API 错误不自动归入此类，
官网仍有文档但当前服务端拒绝的接口也不会被伪装成已完成或权限拒绝。

普通采集可选配置 `throughput_fast_lane_apis` 和
`throughput_fast_lane_every`。快车道只接受已审核、分钟频率等于当前账户上限且对应
数据族已启用的接口；按接口持久化轮转，并继续按近期三次、历史一次的比例选取任务。
例如 `every=2` 只让每两个调度机会中的一个进入快车道，另一个仍走原有数据族公平
轮转。共享账户/API 限速、已观察冷却、每日总量、任务重试与原始证据写入均不变；
配置为空时调度行为完全保持原样。

`acquisition_pipeline_depth` 默认 1，有界在线验收值可设为 2、3 或 4。
深度大于 1 时默认仍只使用一个 HTTP 执行线程：主线程在上一请求进行时等待并持久化下一条合法的
账户/API 频控槽，最多预取 `depth - 1` 条任务，从而重叠网络时间和限速等待，
不形成未经频控预留的请求突发。预取任务在请求前以
`inflight` 状态和频控槽一起提交；进程异常退出后，新 owner 只把该状态恢复为
`pending`，已提交的频控槽继续保留，因此恢复不会绕过限速。轮次报告中的
`acquisition_pipeline` 给出深度、HTTP worker 数、队列高水位和崩溃恢复任务数。
启用深度 2 前后须在完整生产轮次比较真实请求数、`rate_limited` 响应和失败阶段。
当完整轮次证明线程解释器争用使实际睡眠显著高于请求睡眠时，可将
`acquisition_capture_execution` 从默认 `thread` 灰度设为 `process`。它只把同一个
HTTP worker 和一条预取任务移入独立进程，Token 通过进程初始化管道传递，不进入命令
参数、配置或报告；账户/API 频控预留、结果事务和唯一写入者仍由原主进程控制。
当 HTTP+原始对象落盘已成为真实瓶颈时，可在 process 模式下将
`acquisition_capture_workers` 从默认 1 逐级在线验收为 2、3 或 4，且 worker
不得超过 pipeline depth。主进程仍在每次提交前逐个持久化共享账户和 API gate，因此并发
worker 只重叠已合法预留的网络/落盘时间，不放宽分钟频次、
接口特殊上限或每日配额。报告中的 `http_workers` 必须与实际值一致。
并发池按最先完成的响应回收并补入下一条已合法预留的请求，避免慢队头让其他已完成
响应和空闲槽等待；提交顺序可以变化，但每个 response 的 attempt/job 事务仍由主进程
逐条完成。状态中的 `completion_order=first_completed` 用于核对实际运行策略。
本机 `pipeline.sqlite` 与 `documents.sqlite` 默认使用 `WAL + FULL`：WAL 减少高频小事务
反复创建和删除回滚日志的成本，FULL 保留请求前 gate 和响应后结果提交的断电耐久边界。
迁移到不支持 SQLite WAL 共享内存语义的 NAS 文件系统前，必须先停唯一写入者并验证挂载；
需要回退时在节点私有环境设置 `QM_TUSHARE_SQLITE_JOURNAL_MODE=DELETE`，不能在进程运行中
切换，也不能用降低 `synchronous` 换取吞吐。
若 `account_gate_requested_sleep` 与 `account_gate_sleep` 继续显示同进程文档线程阻塞
限速调度，可将 `document_worker_execution` 从默认 `thread` 灰度设为 `process`。
它不改变文档锁、任务数据库、下载并发数或采集/发布顺序，只隔离 Python 调度；worker
状态会报告实际使用的 `document_execution`，配置值仅允许 `thread` 或 `process`。
文档下载并发允许 1 到 16，解析并发允许 1 到 4；提高并发不改变每轮总阶段数、100 秒总
预算、单下载 20 秒预算、256 MiB 上限、磁盘保护或终态冷却。生产只能从已验收档位
逐级灰度，并同时比较完成下载数、失败分类、结构化采集请求数、CPU 与磁盘余量。
`document_overlap_parse_download` 默认关闭。启用时 PDF 解析可与现有有界下载槽重叠；
`document_parse_workers` 默认 1、上限 4，只有重叠已启用且下载 worker 大于 1 时才允许
多路解析。每个解析子进程继续独立承受 1 GiB 常驻内存、15 秒 CPU、5000 页和输出上限；
SQLite claim、attempt 和完成事务仍只由主线程写入，每轮阶段总数与截止时间覆盖全部在途
任务。下载采用四批槽位的有限领先量，避免以扩大未解析积压换取表面吞吐。状态中的
`parse_workers`、`overlap_parse_download` 和 `parse_download_overlap_seconds` 用于生产
灰度验收；下载 worker 为 1 时保持原串行路径。
`document_worker_max_documents` 的配置上限为 2500；它只限制一轮内完成并提交的下载与
解析阶段数，仍受 100 秒总截止和全部资源边界约束。生产从已验收的 1000 逐步灰度，
不能把提高阶段上限解释为延长运行时间或放松单文件限制。
文档注册记录上限允许 1 到 20,000，但仍受独立的最长 20 秒配置校验、生产
5 秒硬截止、100 条事务分块与持久化游标约束；记录上限不是无界扫描授权。
安装器为归档 LaunchAgent 设置 `ProcessType=Interactive`。本机一次性无网络探针实测，
默认/Standard 进程的 120ms 睡眠中位数约 262ms，Interactive 约 126ms；因此该键用于
避免 macOS 合并账户频控定时器。它不提高配置的 RPM、不增加 HTTP worker，生产仍须
以 `account_gate_requested_sleep`、实际 sleep、供应商限频结果和 CPU 占用共同验收。


2026-09-17 云端旧归档释放验收：冻结清单中的 1,209,626 个不可变文件已按
Mac 再验证收据删除，清理服务终态成功。随后对 11 个旧 SQLite 源库使用只读连接
重新 backup（包含 WAL），输出逐个匹配 Mac 冻结数据库 SHA；持有迁移/写入锁，
确认源文件 inode、大小、mtime 未变且检查点哈希匹配后，精确释放 22 个源库及
检查点文件，共 34,884,812,800 逻辑字节。未删除 Mac 文件、研究缓存或完整备份。
该次受限运维脚本及 SOURCE_DATABASES_VERIFIED.json、DATABASE_RETIREMENT_PLAN.json、
DATABASE_RETIREMENT.json 保存在云端原归档 `.migration/` 对应检查点中；
Mac 私有验收汇总为 `~/Library/Application Support/QuantMind/tushare-cloud-retirement-verified-20260917.json`。
旧归档剩余约 648 MiB 的停写标记、清单和运维证据，研究缓存约 1.5 GiB；
文件系统可用约 352 GiB（验收时点值，非容量承诺）。完整备份约 306 GiB 暂时保留，
待下一份正常备份校验成功后整体轮转，不就地删改 COMPLETE 快照内容。
清理后实际云端应用路由的 daily/adj_factor/ci_daily 均从研究缓存返回记录，
upstream_calls=0；应用与 QuantDB worker 启动时间不变，健康检查正常。
这项验收不代表全量历史采齐，也不代表已完成外部认证 HTTP 或 UI 验收。


2026-09-19 附件补采边界更新（取代上文旧的 256 MiB 配置上限）：
生产单文件上限现为 320 MiB，默认值仍为 25 MiB。每轮提交前按实际剩余空间减
300 GiB 预留量计算可接纳阶段数，包含下载及解析输出预算。扩大上限后，只有
旧大小限制失败且声明长度能容纳的附件可以立即重试；来源失败仍遵守原冷却。
到期重试优先于新下载，避免数百万待下载记录按 ID 排序时长期挤占重试任务。
原始响应和历史 attempt 保留。大附件配置下总下载预算最多 120 秒，且不超过
整轮剩余时间；默认大小配置仍为 20 秒。任务租约覆盖传输预算，单次 socket
等待仍为 20 秒，解析限制保持不变。此修复对应提交 47cc50ed。
实现提交为 838df986、05037dcd；附件测试 99 项、worker 测试 14 项通过。
配置已部署到 Mac 原生采集进程；超大文件是否成功仍须以实际落盘及哈希验收，
提高上限本身不代表文件已完整取得。
