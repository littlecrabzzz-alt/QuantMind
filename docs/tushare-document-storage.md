# Tushare 原文保存与 PDF 逐页提取

2026-09-09。`backend/shared/tushare_documents.py` 是无数据库、无队列的下载/提取组件，接入目标沿用 [总计划](tushare-integration-plan.md)。此子任务只做模拟网络与临时目录验证，未读取生产凭据、访问真实原文、调整依赖或部署；主任务负责云端调用、持续补齐和发布。

```python
from backend.shared.tushare_documents import fetch_document
result = fetch_document(source_url, "/data/tushare", max_bytes=25 * 1024 * 1024, timeout=20)
```

`status=downloaded` 仅表示本次接收到的 PDF/HTML 字节已经保存。结果另外包含 `source_url`、`final_url`、`redirects`、UTC `fetched_at`、`http_status`、`document_sha256`、`mime`、`validation_status`、`parse_status` 和 `files`。`files` 是元素为 `{path,sha256,bytes,mime}` 的列表，路径相对于传入根目录。调用者须持久化整个结果，才能保留 URL、版本与抓取时间的证据链。

原始文件写入 `attachments/<原始字节SHA256>.pdf` 或 `.html`。解析结果按其自身内容哈希写入 `extracted/<SHA256>.json`，其中包含原文哈希、解析器及版本、页数、`pages: [{page_number: 1, text: "..."}]`。相同字节只保留一个文件，解析器升级可产生新的提取对象，旧结果保留。通过临时文件 fsync 后原子创建硬链接，不覆盖已有对象；已有同名内容损坏或符号链接会返回错误，不能静默替换历史证据。

## 网络约束

- 只接受标准端口的公共 HTTP/HTTPS URL；拒绝 URL 用户名/密码、控制字符、反斜线、非标准端口、localhost、私有/环回/链路本地/保留/组播 IP，并拒绝 IPv4 映射与 IPv6 过渡地址。DNS 同时返回公共与内部地址也拒绝。
- 每次请求及最多三次重定向分别验证目标。解析后直接连接已经检查的数值 IP sockaddr，连接阶段不再次解析域名，因此不能通过 DNS 重绑定切换到内网。HTTPS 仍以原始主机名完成 SNI 和证书验证，未关闭 TLS 校验。原 URL 是 HTTP 时保留其传输属性，不声称具有 HTTPS 的来源真实性。
- 使用标准库直接连接，不读取代理设置、不携带 Cookie、Authorization、Tushare token 或 Referer；服务端 Cookie 不复用。安全约束不能被重定向绕过。
- 流式读取最多 25 MiB，可由调用者调整；预先检查 Content-Length，同时检查实际字节数，拒绝截断、非 200 状态及未请求的内容压缩。只支持 PDF/HTML，其他附件类型记录为不支持，后续扩展不能把它们算作完成。
- `timeout` 为单次 socket 操作和独立解析进程的超时，不是包含 DNS 在内的全任务截止时间。DNS 耗时受系统 resolver 控制；父作业仍须配置总体执行时限和可重试检查点。

这层使用 Python [http.client](https://docs.python.org/3.10/library/http.client.html) 提供 HTTP 协议处理，连接只替换为已经校验的直接 socket；HTTPS 使用默认可信证书上下文和主机名验证。

## 下载、验证和解析状态分别判断

| 状态 | 含义与后续处理 |
|---|---|
| downloaded / parsed | 字节已落盘且提取出文本；仍需抽查版面、页码和原文内容 |
| downloaded / no_text | PDF 可打开但没有文本层，需要 OCR 或人工评估，不能假设空文档 |
| downloaded / encrypted | 原始 PDF 保留；没有破解或绕过加密，提取未完成 |
| downloaded / parse_unavailable | pypdf 不可用或无法设置资源限制；保留文件，稍后在有条件的执行环境解析 |
| downloaded / parse_failed、parse_timeout、parse_limit | 字节保留，解析单独重试或换工具；不把它计入已解析数量 |
| downloaded / not_applicable | 原始 HTML 保存；不执行脚本、不渲染为可信页面，也尚未进行正文抽取、附件发现或内容真实性判断 |
| pdf_content_mismatch、mime_content_mismatch | URL/头声称 PDF，但内容不符；或 PDF 内容与声明的 HTML 冲突；拒绝将错误 HTML 当成 PDF 发布 |
| size_limit、incomplete_download、http_error、download_error | 本次下载未完成；结果保留错误分类及 HTTP 状态，由父队列安排重试 |
| non_public_address 等 URL 错误 | 没有访问该目标；作为不可自动下载的缺口继续其他作业 |

`validation_status=pdf_envelope_only` 表示只有 `%PDF-` 与结束标记检查；不能证明 PDF 完整有效。解析器成功打开之后才是 `pdf_structure_valid`。HTML 使用 `html_content_unverified`：HTTP 200 的登录页/错误页仍可能是合法 HTML，须在业务侧核对是否为所需原文。PDF 签名正常但解析失败也保留原始字节，避免解析器兼容问题导致原文丢失。

PDF 提取在独立 Python 进程中完成，生产路径尝试限制 1 GiB 地址空间、15 秒 CPU、5000 页和 8 MiB 提取文本，另有父进程超时；子进程只保留最少环境变量，不继承 token 或代理配置。资源限制无法设置时返回不可用，不退回无边界解析。这是资源隔离，不是针对任意解析器漏洞的完整 OS 安全沙盒。

[pypdf 文档](https://pypdf.readthedocs.io/en/5.7.0/user/extract-text.html) 提醒压缩 PDF 的展开和文本提取可能消耗大量内存，并且不提供 OCR。文本结果不能替代版面核对，也不能把抓取时间当历史发布时间。

依赖现状：主项目 requirements 未声明 pypdf；`rd-agent/requirements.txt` 已列出，Mac 本次可导入。本组件不安装依赖或改 requirements；云端主执行者需核对实际环境。Mac 的 RLIMIT_AS 不可设置，本次真实隔离调用返回 `parse_unavailable/resource_limits_unavailable`，符合保守边界；仅在测试中对自行生成的已知 PDF 直接运行提取核心，以验证页码和原始文件关联。正式非可信 PDF 不使用此测试绕行。

## 集成和未完成项

父队列按来源 URL/原始记录建立持久任务，下载与解析分别记录重试。对于 pdf_url 或已知应为 PDF 的记录，另要求 result.mime 为 application/pdf；无扩展名的下载 URL 返回 HTML 时，本组件不能凭 URL 推断原文类型，不能由调用方将其记成 PDF 完成。将结果全部 `files` 纳入同一不可变 release，Mac 镜像校验所有附件和提取对象后才切换版本；仅同步结构化元数据不能算原文完成。发布前验证每个对象的大小和 SHA-256，不能仅相信下载函数曾成功。

需要继续推进：真实公告和研报各一份下载/提取及原文页码核对；HTML 内的 PDF/其他附件发现；扫描件 OCR；超过当前单文件/解析资源上限的专用批次；加密文档、坏链、过期链接、非标准端口和上游不可达分别留缺口。这些未完成项不改变可获取原文尽量全历史保存的目标，也不阻塞其他来源。

本次验证命令为 `python3 scripts/test_tushare_documents.py`，7 项模拟网络测试覆盖 URL、混合 DNS、逐跳校验、重定向上限、IP 固定/TLS 主机名、流式大小限制、截断、HTML 伪装 PDF、解析失败保留、幂等与损坏/符号链接拒绝。自行生成两页 PDF 提取后核对文本/页码，第一页面经 Poppler 渲染查看。该结果不证明供应商真实 PDF 可获取或云端解析依赖已经就绪。
