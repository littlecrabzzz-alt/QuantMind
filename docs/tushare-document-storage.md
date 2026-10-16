# Tushare 原文、文本与 PDF 退役合同

用途：解释附件状态、受限解析/OCR、已实现的退役 API 及中断恢复。源码实现不等于已在某节点部署或删除过数据；本页不授权真实删除。归档所有权和升级见 [Tushare 运维](tushare-mac-source.md)。

## 保存与状态

`backend/shared/tushare_documents.py` 将原始字节保存为 `attachments/<SHA256>.pdf|html|bin`，抽取文本保存为 `extracted/<SHA256>.json`。对象内容寻址、不可覆盖，结果保留 URL、跳转、抓取时间、HTTP 状态、原文 SHA、MIME、验证/解析状态和文件描述。`documents.sqlite` 持久保存任务、引用和 attempts；固定发布包含便携索引，不以复制活跃 SQLite 供研究读取。

下载、验证、解析和原件可用性是不同维度：

| 状态 | 含义与处理 |
| --- | --- |
| downloaded / parsed | 已有字节和文本；仍需核对页码、内容及用途 |
| no_text、encrypted | 空文本层或加密，不自动当空文档完成 |
| parse_failed、parse_timeout、parse_limit、parse_unavailable | 原件保留，解析未完成；先检查依赖/资源边界 |
| HTML / not_applicable | 原始 HTML 证据，不执行脚本，不等于可信正文 |
| source_challenge | 保存脚本挑战原始证据，不执行 JS、不生成 Cookie、不绕过访问限制 |
| size_limit、incomplete_download、http_error、download_error | 本次下载未完成，保留明确缺口 |
| attachment_status=retired | 原 PDF 已有收据支持的有意删除；成功文本与历史尝试仍保留 |

`pdf_envelope_only` 或 `pdf_prefix_only` 不证明结构有效；`pdf_structure_valid` 才表示解析器成功打开过。空响应、抓取时间和账户已购权限均不证明历史原文完整或当时已知。

## 下载和解析安全边界

只接受公共 HTTP/HTTPS 标准端口，拒绝 URL 凭据、控制字符、私有/保留地址与混合公私 DNS。每次跳转重新验目标，最多三次；连接固定已检查 IP，HTTPS 仍校验证书及原主机 SNI。不继承 Cookie、Authorization、Token、Referer 或代理，不因挑战改浏览器身份。HTTP 来源不声称有 HTTPS 真实性。

默认文件上限 25 MiB，代码允许配置到 320 MiB；流式检查实际大小及截断。扩大配置不代表文件完整。下载任务与单 socket 超时不同，DNS 仍受系统 resolver 约束。终态重试保留原始响应和 attempts，并受冷却/每轮预算控制，不通过无限重试掩盖失败。

解析在独立子进程中进行；当前常量为 1 GiB 内存、90 秒 CPU、5000 页、8 MiB 文本及 32 MiB 输出，另有调用方墙钟限制。Linux 使用资源限额，Darwin 由父进程监测 RSS；无法建立约束时失败，不回退无界解析。这不是完整 OS 漏洞沙盒，文本也不能替代原版式、签章、图表或人工核查。

## 已有 OCR：先暂存，再入库

`backend/shared/tushare_document_ocr.py` 已实现分阶段流程，不是“待实现 OCR”。操作前确认数据允许发给外部模型、依赖工具可用、凭据及模型额度已获授权，并选择与归档写入协调的窗口。

```sh
# 会读取 PDF，并可能向 GLM 发页图；只写独立 staging，不改归档状态
python3 -m backend.shared.tushare_document_ocr stage \
  --root /absolute/archive --staging /absolute/ocr-staging \
  --workers 1 --page-workers 1 --limit 1
# 显式写归档文档状态；不是只读检查，也不删除 PDF
python3 -m backend.shared.tushare_document_ocr ingest \
  --root /absolute/archive --staging /absolute/ocr-staging
```

CLI 默认 `workers=4`、`page-workers=4`，最大在途模型请求为两者乘积；不要只看单个 worker 数。默认模型为 `glm-5.3-flash`，密钥由本机认证命令按需取入内存，不抄到参数或报告。`--max-pages` 仅限制本轮页数，未完成全部页面时只有可续跑页检查点，不生成可退役的完整文本。

ingest 校验 PDF 与 staged 文本关联，在事务中检查所有引用和活动 claim；已进入退役的原件拒绝导入。它保存新抽取对象，保留旧文件，仅移除当前引用中不可用的旧抽取描述。OCR 成功不自动执行退役，也不保证识别质量适合研究或审计。

若本机另有 `maintenance/pdf-text-driver/driver.sh` 等仓库外常驻驱动，先核对实际进程、脚本和私有日志；不要重复启动 OCR，也不要把 staging 循环当作已完成 ingest 或退役。已有 `maintain.py`、hold 清单和删除收据属于该节点的维护状态，不能随代码同步或用本页示例覆盖；停归档、入库和退役仍须单独授权维护窗口。

## PDF 退役的实际接口

`backend/shared/tushare_attachment_retirement.py` 已实现以下库入口，无独立退役 CLI：

```python
build_plan(root, plan_path, *, max_items=10_000, after=None)
apply_plan(root, plan_path, *, confirm_sha, max_items=1_000)
hold_attachments(root, sha256_list, *, reason)
held_attachments(root)
release_holds(root, sha256_list)
```

root 必须显式提供。`build_plan` 只读归档、写一份不可覆盖的新计划；返回计划原始字节 SHA、候选数、逻辑字节和续扫游标。每次最多扫描 10,000 个候选标识，不仅限制输出；`next_after` 非空时用新计划继续。它不调用供应商、不下载、不删文件。

候选必须是安全路径下的普通 `attachments/<SHA>.pdf`，实际 SHA/大小与所有文档别名一致；全部别名处于 downloaded/parsed、结构验证成功，无活动 claim。每个引用的 extracted 对象必须哈希/大小正确、关联相同原 SHA，页码连续、页数一致且至少一页非空文本。孤儿、缺原件、未知字段证据不足、未解析/加密/空文本以及 held 项均排除；不能只按扩展名或 parsed 计数删。

法律留存、人工审计和外部研究需要的原件先按 SHA 设置 hold。hold 不自动迁移仓库外需求；操作人仍需盘点固定研究目录及外部消费者，不能声称所有研究天然不受影响。

## 删除顺序与故障恢复

只有审核精确计划并明确授权删除后，才把计划原始字节 SHA 作为 `confirm_sha` 传入 `apply_plan`。它重新核对 root/authority 身份、路径、状态和整个有界批次，不接受别的根或篡改计划。

1. 非阻塞取得 `pipeline.lock → documents.lock → .archive-worker.lock → .archive.lock`；锁忙返回 `retirement_busy`，不要删除锁文件绕过。
2. 在现有 documents.sqlite 中耐久提交 prepared 意图，再逐项重验原件及保留文本、unlink PDF 并 fsync 目录。
3. 保存内容寻址的不可变批收据到 `documents/<SHA>.json`，随后提交 retired 和文档可用性；收据不是 PDF 备份。
4. 中断后保留同计划、账本、文本及收据，以相同 `confirm_sha` 重跑。缺文件但有本次 prepared 证据才可补完；无意图的缺失仍失败。`in_progress` 继续有界执行；`complete` 重入不重复删除或新增收据。

prepared 未完成时发布/归档扫描以 `retirement_in_progress` 拒绝继续，不把中间态洗成损坏或成功。收据/文本损坏仍报错。完成后安排归档 rescan、文档索引、固定发布和逐文件 verify；不能仅凭 deleted_now 宣称全链路验收。逻辑字节不等于实际释放块，硬链接、APFS 快照和备份都可能继续占用。

## 读者、版本与回退

- 新发布的物理 `files` 排除已退役 PDF，另含 `retired_files`、保留文本和收据，并标 `original_attachments_complete=false`；旧 manifest 原字节和 release_id 不改。
- 本节点旧版本查询只能凭路径/SHA/大小精确匹配的有效账本/收据解释缺失，不能放宽普通缺文件、元数据冲突或文本损坏。
- API 先认证及固定版成员校验，再为退役原件返回 HTTP 410 `attachment_retired`；保留文本仍可读，非成员 404。它不会自动补下载或伪造 PDF。
- 结构化研究缓存仅导出 Parquet/observation/schema，不扩展为附件迁移。旧全量镜像明确拒绝退役归档；旧迁移 PRESERVED 仍严格要求原件，不能用文本冒充。
- 删除后只回滚代码会重新产生缺口或补下载风险。恢复原件需另行授权及相同 SHA 全量核验；文字无法重建原 PDF，不保证供应商仍可提供相同字节。

代码阅读入口：`tushare_documents.py`（队列/索引）、`tushare_attachment_retirement.py`（计划/账本/收据）、`tushare_archive.py`（扫描）、`tushare_pipeline.py`（发布/verify）、`backend/services/engine/routers/tushare_data.py`（成员校验/410）。部署兼容性、故障注入及真实规模验收须独立完成，不能把旧红灯设计或一次测试记录当当前部署证明。
