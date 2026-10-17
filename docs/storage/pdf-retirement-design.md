# OCR staging 只读状态观测（status 子命令）

`backend/shared/tushare_document_ocr.py status --staging <dir> [--watch SECONDS]`
解决一个观测缺口：`stage` 只在整份文档完成时打印 `document=N`，一份数百页长 PDF
会让日志长时间不动，无法判断是在推进还是卡死。

分类为互斥集合，按 SHA 去重，优先级 ingested > staged > incomplete。**完成判据复用
`_validate` 与 `ingest_staged` 的真实入库条件**（parse_status=parsed 且存在非空页文本），
只看文件名不算完成：

- `ingested`：`staging/ingested/{sha}.json` 通过校验且可入库，业务可消费。
- `staged_awaiting_ingest`：staging 根 `{sha}.json` 通过校验且可入库但尚未入库（DB 仍
  no_text/encrypted）；OCR 已完成，等待 maintain ingest（24h cadence 或 final drain），
  不是"未 OCR"。
- `ingested_empty`/`staged_empty`：结构有效但 parse_status=no_text 或全空文本——stage
  真实会产出这类文件而 ingest 拒绝入库，单独呈现，不算完成。
- `ingested_invalid`/`staged_invalid`：不可读/损坏/校验失败，单独呈现。
- `staged_overlap_ingested`：同一有效 SHA 同时在 ingested/ 与根（ingest 用 os.replace
  移动，正常不出现）；只计入 ingested 并列出。
- `incomplete_checkpoints[]`：无完整文档的 checkpoint 目录。pages_done 只计通过
  stage 自身页契约（canonical `{n}.json` 且 page_number=n、text 为 str）的页，
  按页号天然去重（01.json 不会重复计数）；损坏/页号不符的页不计完成并列入
  `invalid_page_files`。最近活跃排最前；ingested/staged SHA 遗留的 checkpoint 目录
  是正常残留，绝不计入在途。

约束：严格只读（不建目录、不写 checkpoint、不触发 stage、无 DB 访问、无模型调用）；
`last_checkpoint_age_seconds` 只是观测时间，不据此宣称进程在运行或已停止；
`--watch` 循环重印，Ctrl-C（含刷新瞬间）只停 viewer。测试见
`scripts/test_tushare_document_ocr_status.py`（同 SHA 真重叠去重、空/损坏完成件不计
staged、重复/损坏页不计 done、字节级只读、最近优先排序）。

完成数按有效 SHA 集合差计算；同 SHA 的空/坏副本不会减成负数，也不会遮蔽另一处的有效副本。metadata 缺失时先按 canonical 页号集合去重，`01.json` 与 `1.json` 不会重复计页；完整件 JSON 非对象时归 invalid，不使 status/watch 中断。
