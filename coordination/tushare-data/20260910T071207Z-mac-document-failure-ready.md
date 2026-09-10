# Tushare 附件失败闭环：候选就绪

- 时间、节点、任务标识：2026-09-10 07:12Z，Mac，document-failure
- 状态：待交接
- 分支、worktree、提交：`codex/tushare-document-failure-20260910`，候选 `298bd4a11aa30e3c96ddca42eaaa8252bf11c8e1`
- 分工：只改 PDF 解析回退与对应测试；生产仅短时只读审计，未读凭据、未改配置、未重启或部署。
- 接续：`20260910T070300Z-mac-document-failure-start.md`

原子状态 `2026-09-10T06:56:56Z`：pending 1,075,704、parsed 17,179、parse_failed 93、parse_timeout 24；单批 91.812 秒，24 次下载共 40.049 秒、20 次解析共 46.945 秒、finish DB wait 8.138 秒。最近 5,000 次 attempt 的 3 秒上限只读样本中，当前失败 16 份：4 个 `PdfReadError`、9 个 `parser_process_failed`、3 个 `parse_timeout`。

6 份生产保留 PDF 只读复制到本机 `/tmp` 后 SHA-256 全匹配。同版 pypdf 6.17.0 下，4 个 `PdfReadError` 的 strict=false 回退分别识别出 3/7/3/4 页且正文均为空，准确落为 `no_text`；耗时 0.000937–0.029083 秒。另 2 个大文件继续走 strict，离线核心解析 292/382 页耗时 4.901/5.367 秒。代码仅捕获 `PdfReadError` 在同一个既有受限子进程中回退一次；正常输出不变，二次失败仍为 `parse_failed` 并保留两类错误。原始 PDF、SHA、不可变提取物、重试次数、SQLite 单写者、2 下载/1 解析、15 秒时限和 100GiB 守卫均未改变。脱敏证据见 `docs/tushare-document-parse-failure-audit.evidence.json`。

验证：Python 3.10 全部 `test_tushare_document*.py` 71 项通过；Ruff 通过；JSON、diff check 通过。合入和部署后只需等待当前附件任务自然排空并仅重启 document worker；用主键短读确认仍有一次资格的样本 `04df9c67…` 新 attempt 为 `no_text`、`parser_mode=lenient_fallback`、`strict_error_type=PdfReadError`，原 PDF `039ef73d…` 的 SHA 不变，worker 仍报告 2 下载和 1 解析。其余 3 个已达 5 次的样本不自动重排；本候选不处理 OCR、timeout 或 `parser_process_failed`。回滚只需回退代码，无 schema 或配置恢复。
