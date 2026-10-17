# 授权维护窗口执行与周期维护恢复（第5线收口）

- 节点、任务：Mac，ocr-maintain-window-7c3d；接续 [ocr-driver-cycle-fix-4e71](20261016T193500Z-mac-ocr-driver-cycle-fix-4e71.md)。父/platform 放行一次 native 归档维护窗口。

## 窗口执行（2026-10-16 12:07-12:08 local，37s）

- 前置实况与授权一致：worker com.quantmind.tushare-archive running（PID 91561）、ENABLED 在、pipeline/documents/.archive/.migration 锁空闲、source 无在途。
- 执行修复版 maintain.py（保留原启停状态）：hold 新增 0（**10737 既有 hold 原样保留，未解除**）→ ingest 真实待入库 **8 件** → 按原规则退役 8 PDF/0.0GB（收据 `maintenance/pdf-text-driver/plans/20261016-1207/plan-0001..0003.json`）→ worker 恢复 running（新 PID 7999，ENABLED 未动）。
- 后验：staging root 待入库=0、ingested/=649、OCR driver 全程未中断。

## 数字更正（不改动旧记录，追加澄清）

上轮记录所写"641 份历史完成件待 ingest"为当时误读：641 是 `ocr-staging/ingested/` 的历史累计入库数，不是待入库数；staging root 真实待入库在本窗口前为 **8 件**（已全部入库），现 ingested 累计 649。旧记录保留为当时认知，以本记录为准。

## 周期维护恢复（父指令：driver 内安全 idle 重试，不永久手动）

- `scripts/pdf_text_driver.sh`（提交 ee8d4b8d）：每 cycle 末与 no_candidates 退出处调用 `maybe_maintain`——`.last-maintain` 标记满 `MAINTAIN_CADENCE`（默认 86400s）才跑；失败仅记 deferred、下轮重试；标记初值=本窗口完成时刻（父指定本窗口为 24h 基准，避免与 source 新请求抢写）。
- `maintain.py` 新增两保护（备份 maintain.py.bak-20261016）：① 保留 worker 原启停状态，不再无条件 bootstrap（原本 stopped 则保持 stopped）；② busy 延期预检——worker 状态文件 120s 内有更新（如在途补源）即 `SystemExit(75)` 延期不强停，由 driver 下轮重试。
- 部署副本与 worktree diff 为空；driver 已重启加载（单实例，stage 恢复推进）。

## 状态

第5线代码/运行/维护链路收口完成：配额有界+可见、pdfinfo 回退、排队取消、argv driver、周期维护+busy延期、10737 hold 保留。等待父最终验收。
