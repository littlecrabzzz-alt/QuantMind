# Tushare 公告 PDF 附件退役设计与红灯验收

日期：2026-10-10（设计轮），当前状态更新：2026-10-16。状态：已实现、已部署并在生产运行——退役/分阶段清理/OCR/分页并发/hold 保护已合入 master（c1ae3c26、c37453fe、d2e81f17、808c66d7、5eb09120），历史批次已退役约 13.7 万 PDF/约 69GB，收据在 `~/Library/Application Support/QuantMind/maintenance/{storage-receipts,pdf-plans}`。下文第 1~9 节为设计轮的历史证据，行号对应当轮源码，保留不改；与现状冲突时以本段与 `coordination/tushare-data/` 记录为准。

当前运行入口（2026-10-16）：常驻驱动 `~/Library/Application Support/QuantMind/maintenance/pdf-text-driver/driver.sh`（仅 OCR staging 循环：有界配额退避+显式 `stage=no_candidates`/`stage=quota_exceeded` 标记；**不自动执行归档维护**）；OCR 引擎 `backend/shared/tushare_document_ocr.py`（pypdf 无法读页数时 pdfinfo 回退、失败保持阻塞不伪造；逐页 checkpoint 在 `maintenance/ocr-staging/<sha>/`，完成件 `<sha>.json` 待 ingest）；归档维护 `pdf-text-driver/maintain.py`（停归档 worker→hold→ingest→退役→恢复 worker）仅在明确授权的维护窗口手动执行；定期报告保护名单 `maintenance/periodic-hold-shas.txt`（10737 项）。

以下为设计轮（2026-10-10）当轮记录：

## 1. 现有实现与最小扩展

`tushare_documents.py` 已有文档 SQLite、内容寻址文件、下载/解析状态、引用关系、增量索引；`tushare_archive.py` 已有可续跑扫描与 gap；`Pipeline.publish` 已有固定版本发布与历史清单保留；API 已有认证、清单成员校验和错误转换。复用这些能力，增加附件生命周期记录和收据，让现有链路识别有意删除。不能把 `parse_status` 改成 retired：解析成功的事实与原件是否可用是两个维度。

`scripts/storage_maintenance.py:104`、`:110` 已有计划文件 SHA 确认和收据模式，可沿用操作语义；不能直接调用它的 `rmtree` 实现，因为它面向完整副本目录，不具备 PDF→抽取文本关联验证、文档队列事务和逐文件故障恢复。不要另建采集、发布或同步系统。

## 2. 源码路径审计

行号为本轮读取的主工作树版本。检索使用 `rg -n 'attachments|attachment_path|document_sha256|original_path|pdf_path' backend scripts --glob '*.py' --glob '!test_*'`，再全仓检索 `attachments|\.pdf|original.*files`，并追踪 `manifest["files"]` 的通用读者。下面包含实际 PDF 读取、间接校验、队列入口及相关研究边界；不是把所有出现“附件”的业务都视为 Tushare。

| 代码位置（文件:行号） | 当前行为及直接删除后的结果 | 设计要求 |
| --- | --- | --- |
| `backend/shared/tushare_documents.py:140` `_save`，`:156`、`:158` | 写内容寻址附件；已有同名文件逐字节校验。删后同 SHA 下载可重新创建 PDF | PDF 保存边界检查退役 SHA，不能自动复活原件；HTML/bin 不变 |
| 同文件 `:170` `_parse_worker`、`:205` `_extract_pdf_reader`、`:238` `_extract_pdf`、`:343` `_parse_pdf_darwin`、`:414` `_parse_pdf` | pypdf/子进程实际打开 PDF。缺失会成为解析错误；这些低层函数不负责队列退役决策 | 在调用前阻断退役任务，底层保留正常错误行为 |
| 同文件 `:444` `fetch_document`，`:647`～`:675` | 下载存 PDF、解析、写 extracted，保存 `document_sha256`。单独调用不依赖队列成功状态 | 已知文档不得重新下载；新 URL 若下载后才识别相同 SHA，复用文本并返回退役标记，不再次保存/解析该 PDF |
| 同文件 `:790` `enqueue_documents`，`:886`～`:918` | 同记录/URL/MIME 复用 downloaded/pending/retry；不同元数据创建新任务。当前不会仅因 PDF 缺失而重排已成功记录 | 保留 downloaded/parsed，重复观察复用原文档；不能按 URL 永久屏蔽真正新版本 |
| 同文件 `:1001` `_download_job`、`:1078` `_parse_saved`（读文件在 `:1092`） | 下载子进程可重新落文件；已保存 PDF 缺失在 read_bytes 抛异常，外层可能记 parse_failed 并重试 | 解析入口查生命周期并校验 retained text，返回 parsed + attachment_status=retired，不启动解析器 |
| 同文件 `:1236` `_schedule_terminal_retries`、`:1361` `_eligible_documents`、`:1420` `_claim_documents`、`:1453` `_finish_document`、`:1533` `_run_documents_overlapped`、`:1700` `run_documents` | blocked 重开、pending/retry 下载、下载成功但解析失败/待解析重试；正常 parsed 本来不入选。若错误重置状态或并发提交，可复活工作 | prepared/retired 从领取与终态重试排除；结束事务不能覆盖退役状态；续跑退役不运行 worker |
| 同文件 `:1990` `document_inventory`、`:2028`～`:2061` | v1 枚举现有附件并 stat；缺失文件不枚举，但文档结果仍引用原件 | physical files 不含退役 PDF，另给 retired_files；映射保留历史描述并加可用性 |
| 同文件 `:2079` `_index_setup`、`:2158` `_state_index_triggers`、`:2179` `_index_original_files`、`:2236` `document_index`、`:2328` | 原件索引只插入不删除；PDF 消失并不一定当场报错，旧 document_index_files 仍把它输出给发布器；冷索引则漏掉缺失条目 | 冷/热索引均有退役记录；旧行不再进入物理清单，相关文件分片与状态分片失效重建，不默默漏掉普通丢失 |
| `backend/shared/tushare_archive.py:55` `_safe`、`:71` `_fingerprint`、`:146` `_snapshot` | stat/流式哈希；rescan 将 valid 清零并重新排所有已知路径，含已删除路径 | 退役路径由账本与收据进入扫描，不能只枚举磁盘；正常文件检查不放宽 |
| 同文件 `:445` `_expected_files`（旧 probe 缺元数据在 `:488` 读取）、`:515` `retain_release`、`:613` `_manifest`（`:654` 生成文件任务） | 历史清单继续引用 PDF；retain 继承引用，并不证明文件当前存在；旧 probe 可能直接因缺失报错 | 历史原字节保留；仅精确匹配 path/SHA/bytes 的退役证明替代物理读取，元数据冲突仍失败 |
| 同文件 `:711` `_file`、`:785` `recover_archive`（`:845`～`:860`） | 缺失报 FileNotFoundError，记 gap、任务 gap、files.valid=0 | 完整退役证明通过则任务 done，逻辑 valid=1、storage_state=retired，不计损坏；缺少证明依旧 gap |
| 同文件 `:758` `_progress`、`:871` `archive_inventory` | 仅输出 valid=1 物理 files，统计缺口 | 分开 available/retired 计数，retired_files 显式输出；“无损坏”不代表原件完整 |
| `backend/shared/tushare_pipeline.py:6189` `Pipeline.publish`、`:6274`、`:6430`、`:6457`、`:6473`、`:6612`、`:6625` | 合并前版 files、归档 files、文档索引、历史 metadata，再 retain 前版。只在一个输入处过滤会被后续合并重新带回 PDF；发布本身不逐个哈希所有原件 | 所有合并及版本等价比较使用统一退役投影；最终 files 只含物理对象；retired_files/收据影响版本 SHA |
| 同文件 `:7367` `manifest_at`、`:7385` `verify_data`（`:7392`～`:7393`）；`scripts/tushare_pipeline.py:49` 调用验证 | manifest_at 验清单及路径；verify_data 对所有 files stat/read_bytes，旧 PDF 缺失即失败 | 新清单验收据、文本；旧清单允许本节点已验证退役覆盖，返回原清单，不改 release_id |
| `backend/services/engine/routers/tushare_data.py:81` `_artifact`、`:87`，`:408` `document_text`、`:423` | OBJECT 接受 PDF，text 路由先读取，再对 PDF 返回 415；缺失由 `:52` `_errors` 转 404，其他 I/O 可为 409，并非必然 500。未找到独立 PDF 下载路由 | 成员校验后返回 HTTP 410 attachment_retired；text JSON 继续 200；不伪造 PDF 或触发下载 |
| `scripts/tushare_mirror.py:28` `fingerprint`、`:35` `checked_file`、`:417`～`:464` 全量镜像循环 | 对清单所有对象检查；缺失加入 rsync 清单，来源已删则传输失败，或从其他副本重新得到 PDF | 旧全量镜像不能重启补 PDF；如支持新版清单，先验证收据，再排除退役对象；旧版不识别时明确拒绝格式 |
| `scripts/tushare_archive_migrate.py:54` `inventory_files`、`:68` `digest`、`:188` `verify_checkpoint`（`:205`）、`:371` `verify_preserved`（`:388`） | 遍历全归档及迁移清单逐项哈希 PDF；旧检查点在删除后必然不能通过“原件逐文件保留”证明 | 保留旧证明原文与旧验证的严格语义，不把 retired 伪报为 preserved；未来迁移须创建含退役收据的新基线，不能用旧证明继续清理 |

研究路径已核对：

- `scripts/tushare_research_cache.py:30` 的 FILE 仅允许 parquet/observations/schemas；`:65` prepare（`:83`～`:130`）只构建这些对象的闭包。`:33` checked、`:232` serve（`:256`）、`:290` pull（`:322`）虽是通用哈希/传输，当前可达输入不包含 PDF，删公告 PDF 不应让结构化缓存重下附件，不扩展白名单。
- `backend/shared/tushare_pipeline.py:6241` 的 research scope、`:6442`、`:6459`：研究发布不做文档索引。`backend/shared/tushare_store.py:175` `_dataset`（`:192`、`:203`～`:210`）只验 parquet，`:251`～`:281` 验 observation，不读 PDF。结构化 API 与这些研究入口无需新增附件补采。
- 通用报告研究工具 `alphaagent/components/document_reader/document_reader.py:94`、`:103` 与 `rd-agent/rdagent/components/document_reader/document_reader.py:94`、`:103` 读调用者指定的 PDF；两个 `scenarios/qlib/factor_experiment_loader/pdf_loader.py:68` / `:63` 处理 PDF 报告；两个 `app/qlib_rd_loop/factor_from_report.py:113` / `:105` 枚举报告目录。未找到它们绑定 tushare/attachments 的代码。若外部手动把该目录作为 report_folder，删除会让显式读取失败或目录枚举减少，不能声称研究不受影响；外部调用清单见待确认。
- `backend/services/engine/routers/trading_agents.py:501`、`:612`、`trading_agents/report_exporter.py:191`，以及 qwenpaw_proxy 的 attachments，是研究报告/用户上传文件，未发现 Tushare 公告归档连接，不纳入删除范围。

## 3. 状态、账本与不可变收据

选择在 **现有 `documents.sqlite` 内增加表**，不单建可变 JSON 总账、不加第二个 SQLite：文档状态与退役意图可在同一事务提交，复用 FULL 同步、WAL/DELETE 配置和文档锁。166 万条不能每个扫描都解析所有 documents.result；以路径/SHA 建索引，计划生成用 keyset 分批游标扫描。首次构建关联索引的成本须隔离压测。

建议表（版本化迁移留到实现任务）：

- `attachment_retirement_plans(plan_sha256 PRIMARY KEY, root_identity, plan_path, schema_version, created_at)`：绑定精确计划字节及归档根，计划完整保留，不存凭据。
- `attachment_retirements(path PRIMARY KEY, sha256, bytes, plan_sha256, state, evidence_json, prepared_at, retired_at, receipt_path, receipt_sha256)`；state 仅 `prepared`/`retired`。evidence_json 保存文档 ID、结果摘要、extracted 描述及其来源关联。路径、SHA、大小写入后不原地替换。
- 多文档共用 PDF 的映射用现有 documents/result 与按 SHA 建立的可查询索引；确需实体关联时在同一数据库增加窄关联表，不能靠 URL 推断 SHA。失败/未解析的别名会保守阻止退役。

保持 documents.download_status=`downloaded`、parse_status=`parsed`。退役事务为对应 result 增加 `attachment_status: "retired"`，触发现有 dirty-state 更新；原 files 描述、document_sha256、尝试历史不删改。prepared 不伪装 parsed 完成的新工作，领取入口以账本排除它。

收据复用内容寻址 `documents/<sha256>.json` 与 `_save`：一批完成项一张收据，避免额外 166 万个小文件。内容包含 `schema_version:1, kind:"attachment_retirement_receipt", plan_sha256, retired_at, items`；每项有原 path/SHA/bytes、document_ids、extracted 描述、`status:"retired"`。计划和收据须 fsync 文件与父目录，SQLite FULL 提交；收据只追加，不覆写。导出包含收据和保留文本，不传 SQLite/锁/队列。收据记录删除事实，**不是 PDF 备份**。

归档库另增 `files.storage_state`（available/retired）及收据引用，valid 仍表示“相应证据已验证”，不可让旧调用者将 retired 当作现存文件。inventory 的 `files` 只列物理对象，`retired_files` 单列逻辑对象；旧 valid=0 的普通丢失不能批量洗白。

## 4. 候选判定

逐项满足，任一不满足则排除并给出原因，不能仅依据扩展名或 `parse_status`：

1. 仅归档根直属 `attachments/<64位小写SHA>.pdf`，所有父目录与叶子无 symlink，普通文件；PDF 内容哈希、文件名、保存的 SHA 和 bytes 一致。HTML、bin、临时文件、孤立 PDF 不入选。
2. 对应 documents 的 download_status=downloaded、parse_status=parsed，result 同样为 parsed、validation_status=pdf_structure_valid；raw SHA 与 result.document_sha256、PDF 描述一致。no_text、encrypted、parse_limit、parse_pending、失败/不可用/未尝试均不算“成功抽出文字”。
3. result.files 明确列出 extracted/<sha>.json。实际存在、普通文件、非链接，字节数和实际 SHA 与文件名及描述一致；UTF-8 JSON 对象，parse_status=parsed、document_sha256 等于这个 PDF SHA。
4. pages 为合法页列表，page_number 为连续正整数、text 为字符串、page_count 与列表一致，至少一页非空白文本；保留 parser/parser_version 等来源。不能把另一个文档的文字作为替代。
5. 同 PDF 的所有当前文档别名都已成功并通过上述关联校验。多个有效抽取版本全部保留在计划中；历史失败尝试保留但不等于当前别名失败。活跃 claim、下载/解析/发布占锁时不得删除。
6. 若抽取文本在规划后变化、文档状态回退、新增失败别名，执行时重新判定拒绝。已经缺失但没有 prepared 意图的 PDF 永不补造退役证据。

## 5. 执行顺序与中断恢复

本单不执行这些步骤，也不授权实现任务跳过部署验收。

1. 在 Mac 唯一归档所有者上先部署全部读者兼容性，正常排空文档工作；云端不得因此获得供应商补采权限。先小批临时夹具验证，再生成真实计划。使用已有 authority 校验，测试库函数只接受显式 root，绝不默认真实路径。
2. `build_plan` 只读现有文档/附件；写指定的新计划文件，不更新队列或退役状态。以路径排序，每份最多 10,000 项（默认），返回计数和候选字节，后续 `after` 游标分批。计划写 schema_version、root_identity（规范路径，真实执行还绑定 authority 身份）、items、excluded 计数及 next_after。不可覆盖旧计划。
3. 操作者/上层任务审核实际清单后，把**计划原始字节 SHA256**作为 confirm_sha 交给 apply。此 SHA 不是 PDF SHA；执行仍逐个重新哈希 PDF 和文本。复制到其他归档根、篡改计划、路径逃逸或重复路径都拒绝。
4. 使用既有锁顺序 `pipeline.lock → documents.lock → .archive.lock`，非阻塞获取，忙则退出且不删。使用短批次，不一次锁住 1.2T。入口部署协调现有 `.archive-worker.lock` 所有者；不加互相反向嵌套的锁。直接离线辅助脚本也须遵守此约定。
5. 当前执行批先重验所有项，再逐项处理：写 `prepared` 和完整证据并持久提交；使用固定目录 FD、O_NOFOLLOW 打开 PDF，核对 inode/size/mtime/ctime 与 SHA，在 unlink 前重验身份与文本，unlink 后 fsync attachments 目录。普通异常不继续删下一个文件。
6. 为已删除项写不可变批收据，持久化后事务更新 retired、result 可用性和索引 dirty。收据写失败、磁盘满或进程死亡时保持 prepared；不提前报完成。下次同一 plan_sha 幂等恢复：文件还在则重验后删；文件不在但有本次 prepared 证据则核验保留文本后补收据/提交，已 retired 则不重复删除/出收据。收据已落盘而 DB 未提交时以确定的内容/关联识别已完成批并补齐。
7. SQLite 与文件系统不是原子事务，prepared 必须先于 unlink；不能仅凭“文件不在”判断成功。prepared 遗留期间发布/扫描返回明确 `retirement_in_progress`，不记 missing gap、不发布混合版本；先续跑或处理故障。收据损坏是证据错误，不享受 missing 豁免。
8. 退役完成后跑归档 rescan、文档索引、全量新发布和 verify_data。失败保留意图与收据、停止后续删除，不回滚为“文件仍在”。释放空间以真实文件系统块统计为准，hardlink/快照可能使释放量小于 bytes 总和，不为本次退役自动删除备份。

## 6. 各环节的交付语义

- **扫描**：读取 ledger + 校验过的收据，精确比对历史清单期望；即使 archive.sqlite 从零建立也能识别 retired。退役 PDF 不记 missing gap、不标损坏，任务完成；extracted、收据损坏/缺失仍产生 gap。元数据不符、越界或无收据不得豁免。
- **索引**：available 文件分片排除退役 PDF；退休描述保留在 retired_files/对应分片，状态映射提供 attachment_status；旧尝试和旧分片原样保留。变更须使热缓存 dirty，不能只改目录扫描。未退役缺失应报明确错误或由归档 gap 披露，不借本设计忽略。
- **发布**：新 manifest 增加 `retired_files`（path→原 SHA/bytes/status/extracted/receipt 描述），files 仅含真实现存对象，并包含所引用 extracted 与收据。对前版、archive、index、retain 所有来源使用同一投影；retention 的 inherited 严格比较须在退役投影前匹配原始元数据，不能触发 “Conflicting inherited file metadata”，也不能放宽其他对象校验。新版本标明原件不完整，不宣称 full original archive。
- **历史版本**：不编辑任何已发布 manifest/shard。其原 SHA 与 release_id 不变；读者依据本节点账本/已验证收据叠加“当前原件不可用”。旧版本首次转移到空节点不能只拿旧 manifest 忽略 PDF：必须显式提供由当前可信发布绑定的退役收据，或明确拒绝；不重启旧镜像兜底。后续迁移使用新基线，旧 PRESERVED 证明仅表达当时事实。
- **队列**：保留成功状态与重用索引，领取、terminal retry、finish 均尊重 prepared/retired；同观察再次入队和相同元数据的新观察不新增下载。若全新 URL/记录无 SHA 关联，无法事先断定其内容与退役 PDF 相同，允许正常新采集，但识别 SHA 后不能重新保存/解析退役内容。不得用 URL 的相等把供应商新版文档吞掉。
- **API**：先认证和 release 成员校验（旧 files 或新 retired_files），再判断退役。返回 HTTP 410，detail 至少 `{code:"attachment_retired", path, sha256, receipt, extracted}`。列表显示退役原件和可用文本，文本 JSON 仍正常分页。非该 release 成员仍 404，不泄露其他版本内容；无退役证据的 missing 仍 404、损坏仍 409，不自动下载。不新建一个虚假的 PDF 下载路由。
- **规模**：复用现有分片机制；一份有界计划/一次 apply 批一个收据，避免每个 PDF 一张 JSON。retired_files 逻辑映射在现有平面 manifest 中可能很大，先沿用现有流式序列化；索引分页复用分片。实测超内存预算才增加 descriptor 分片版本，不在本轮另建通用存储框架。

## 7. 测试调用契约

计划新增模块 `backend.shared.tushare_attachment_retirement`，本轮不创建。所有库入口的 root 必须显式传入；不得隐式读取用户家目录、环境部署归档或运行 worker。

```python
def build_plan(root: Path, plan_path: Path, *,
               max_items: int = 10_000, after: str | None = None) -> dict: ...
# 写一次完整、不可覆盖的计划 JSON；只读 root 的业务状态。
# 返回 plan_sha256, candidate_count, candidate_bytes, next_after。
# items[]: path, sha256, bytes, document_ids(排序唯一), extracted(完整文件描述列表)。
# extracted 描述为 {path, sha256, bytes, mime}，items 另带重验的结果摘要。

def apply_plan(root: Path, plan_path: Path, *, confirm_sha: str,
               max_items: int = 1_000) -> dict: ...
# 返回 status('in_progress'/'complete'), remaining, deleted_now,
# receipts(本计划至今所有已提交批收据描述，顺序稳定)。
# 重复 complete 调用 deleted_now=0，receipts 不增加。

def _unlink_verified_pdf(root: Path, item: dict) -> None: ...
# 小型内部文件操作边界，不提交数据库。由 apply 在 durable prepared 之后调用；
# 重新核验并只删除该 PDF，fsync 目录。测试在返回后注入 KeyboardInterrupt。
```

错误类型 `ValueError`，message 使用稳定原因码：`confirmation_sha_mismatch`、`extracted_checksum_mismatch`、`pdf_checksum_mismatch`、`unsafe_path`、`pdf_missing_without_intent`；其他原因例如 `document_state_changed`、`root_identity_mismatch`、`retirement_busy` 同样明确。规划中的不合格对象用排除原因报告，执行中不合格则拒绝继续。

沿用以下现有签名，只扩展返回内容：

```python
recover_archive(root, max_items=200, max_seconds=5, *,
                rescan=False, rescan_releases=False) -> dict
archive_inventory(root) -> dict  # 新增 retired_files；files 仅可读取对象
document_inventory(root) -> dict
document_index(root) -> dict    # 两者新增 retired_files，与 archive 同一描述格式
enqueue_documents(root, observation, api_name, records, fields, *, deadline=None)
_parse_saved(root, result, timeout) -> dict  # 退役返回 attachment_status='retired'
_claims_setup(db, timing=None)
_eligible_documents(db, phase, now, limit)
_schedule_terminal_retries(db, *, now, interval_seconds, max_documents, max_bytes)
Pipeline(root, catalog).publish(*, research=False) -> str
verify_data(root, release_id) -> dict
document_text(release_id, path, page=1, page_size=20, char_offset=0, max_chars=20000)
```

测试复用 `_document_db(root)`、`_save(root, directory, suffix, payload, mime)` 和 `_json(value)` 制造临时数据。PDF 字节只是有哈希的原件占位，夹具表达“此前已解析成功”，不声称测试了真实解析质量。API 测试直接调用真实路由函数（显式所有分页参数），patch 部署根查询与 ROOT；没有发请求到真实服务器，也没有覆盖鉴权验收。

覆盖包括：成功候选与双 SHA；未解析/失败/空文本/加密/结构未验证；extracted 缺失/损坏/关联 SHA 不符；PDF 损坏/孤儿；共享 SHA 别名；confirm SHA 错及计划改字节；执行前文本/PDF 变化、符号链接、无意图缺失；有界续跑和 unlink 后事务前中断；旧索引缓存、旧清单、归档 rescan；普通丢失不豁免；退役后文本丢失仍 gap；重复观察不重排、无可领取工作、不重解析；真实发布器前后版本与 verify_data；API 410、文本 200、跨版本非成员 404。

测试顶层只有标准库，待实现模块在 setUp 内 import，因此 pytest 可收集全部测试；当前执行在该 import 处失败，不 skip/xfail，不提供假实现。收集命令为 `PYTHONDONTWRITEBYTECODE=1 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest -o addopts= --collect-only -q -p no:cacheprovider scripts/test_tushare_attachment_retirement.py`，已实际收集 19 项（退出码 0）。关闭仓库默认 coverage 附加参数是为避免生成本单范围外产物；首次未覆盖 addopts 的收集因 coverage 参数退出 4，未运行测试。

同环境去掉 `--collect-only` 并加 `--maxfail=1`，实际在新模块 import 处报 `ModuleNotFoundError: No module named 'backend.shared.tushare_attachment_retirement'`（退出码 1），符合红灯预期。该检查不运行任何测试主体。语法检查通过不代表这些行为已实现。

## 8. 后续实现函数与估算

这是改动量估算，不是本单要修改的文件清单；新增依赖为零。

| 后续修改位置 | 最小修改范围 | 预计净新增/修改行 |
| --- | --- | --- |
| 新 retirement 模块 | 有界计划、重验、prepared/retired 恢复、收据、共用查询/投影 | 300～450 |
| tushare_documents | `_document_db` 迁移；`_save`/`fetch_document` 保存防复活；`_parse_saved`；enqueue/eligible/retry/finish；inventory/index 及 dirty triggers | 150～240 |
| tushare_archive | `_db`、`_snapshot`、`_expected_files`、`_file`、`_progress`、inventory；保留原始 manifest 语义 | 100～170 |
| tushare_pipeline | publish 的所有合并/等价比较/retain 边界；manifest_at 新字段校验、verify_data 双清单语义 | 90～150 |
| tushare_data API | `_artifact` 与文档列表可用性，410 错误体 | 25～50 |
| 镜像/部署与操作说明 | 旧客户端拒绝不支持的语义、更新安装副本模块列表；新迁移基线说明 | 40～90 |

合计约 705～1,150 行，不含扩充测试。文件系统安全、掉电持久性和历史版本继承占主要成本，不能以一个 `exists()` 判断替代。结构化研究缓存不扩展功能，旧迁移严格校验不改为允许缺失；不自动启动或恢复旧任务。

## 9. 风险、回退和待确认

**不可逆边界**：unlink 后仅凭文字无法重建原 PDF 的签章、表格、图片、版式，也无法升级解析器重新抽取。业务回退只能显式重新下载（或另行授权从确有原件的备份恢复），不保证供应商 URL 可用或返回同一字节。同 SHA 经全量校验后才能作为原件恢复；不同 SHA 必须新版本，原 retired 收据永久保留。恢复应有独立操作记录，不能删账本伪造“从未退役”。

只回滚代码而不恢复原件会重新产生 gap/下载：上线顺序必须先兼容读者后删除，删除后不能部署不认识退役的旧版。跨进程/掉电中断、SQLite 损坏、硬链接占用、磁盘满需要在实现阶段补故障注入；本文件的异常测试不是断电持久性证明。

待确认（本轮不提问，不访问真实数据）：

1. 真实 166 万个 PDF 中有多少满足严格 parsed/结构验证/非空文本条件，是否存在缺少旧字段但确有文本的遗留记录。默认不退役这部分，不能用猜测补齐证据。
2. 是否有仓库外研究、人工审计或法律留存需求必须保留原件，以及哪些固定研究目录实际引用这些 PDF；默认不改固定研究输入，不自动跟随切换版本。
3. 用户提供约 1.2T 是逻辑大小还是实际可释放块；硬链接、APFS 快照、备份副本实际占用未测量，本设计不承诺释放同等空间。
4. 全量平面 manifest 加 retired_files 在生产规模的内存、序列化时间，以及 Mac/NAS 的 SQLite/fsync/锁语义；先以有界计划与现有分片压测，再定批量大小。上述行数是设计估算。
5. 测试暂未穷举执行前进程锁竞争、目录 FD 替换竞态、收据 fsync 失败、SQLite commit 失败、冷节点收据导入、镜像传输与掉电恢复；实现阶段删除真实 PDF 前须补齐这些验收。库 API 的单测不替代真实运行窗口、唯一所有者检查和远端消费者兼容验证。
