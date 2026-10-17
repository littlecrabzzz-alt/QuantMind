# PDF/OCR 驱动修复与恢复（第5线）

- 节点、任务：Mac，ocr-quota-recovery-9d2f；状态：已部署并真实推进，验收达标。
- 负责范围：仅 OCR staging 链路与文档状态；不动归档维护窗口、不改 platform 独占文件。

## 根因（现场取证）

- 旧 stage 进程（已 27h+ 零推进）栈取证：唯一工作线程停在 `time_sleep` 配额循环，其余线程全部等 future/队列；无网络连接、无子进程。`stage_document` 的 `while True: except QuotaExceeded: sleep(retry_after)` 无上限、无日志，单页长 sleep 劫持整个管线（上轮同因被 24h timeout 杀死后重演）。
- 单发真实页探测 25~28s 成功、16 并发全部 429 → 判定为并发限流而非账号额度耗尽。
- 11 个 sha 每轮 `DependencyError` 无限重试：pypdf 读不了这些 PDF 的页数；实测 pdftoppm/pdfinfo 可正常处理，属页数获取缺陷，非坏件。

## 本次变化

- `backend/shared/tushare_document_ocr.py`（worktree 分支 `codex/ocr-quota-recovery-20261016`，提交 db7d1c7c；运行副本已同步并留 `.bak-20261016` 备份）：
  - 配额等待有界化：单次 sleep 上限 120s+抖动（避免同步惊群），累计 1800s 后 `QuotaExceeded` 上抛，cycle 打印 `stage=quota_exceeded` 干净退出；每次等待有 WARNING 日志（sha/页/时长/累计）。
  - pypdf 读页数失败 → pdfinfo 回退（native 工具：`/opt/homebrew/bin/pdfinfo` → poppler 25.12.0；渲染 `pdftoppm` 同源）；pdfinfo 也失败则 RuntimeError 保持阻塞，不伪造页数、不吞错。
  - `run()` 区分 `QuotaExceeded`（上抛中止）与其它异常（按真实失败记录）；结束时打印 `stage=no_candidates`/`stage=summary` 显式标记。
- `maintenance/pdf-text-driver/driver.sh` 重写：仅 staging 循环；配额退出→1800s 退避；无候选→退出；**不再自动执行 maintain.py**（归档维护仅在授权窗口手动跑）；并发降为 1 文档×2 页（实测 16 并发必 429、单发可用）。
- 文档更正：`docs/storage/pdf-retirement-design.md` 头部状态改为"已实现/部署/生产运行"并写明当前入口；`docs/local-market-source.md` Tushare 行更正为研究版与全归档均 86400s。

## 验证（真实运行，非 mock）

- 回归：`scripts/test_tushare_document_ocr*.py` 14 通过（新增配额有界/回退/不伪造 4 项）；ruff 通过。
- 生产实跑：driver（pid 98445→stage 98452/98453）重启后 `document=1 pages=22`、`document=2 pages=31`——正是原 DependencyError 两份（sha 0050f24e/00e65757）经 pdfinfo 回退后由 glm-5.3-flash 全量真实转写，完成 JSON 落 `ocr-staging/<sha>.json`（内容抽验为真实公告文本）；逐页 checkpoint 保留于 `ocr-staging/<sha>/`，断点续跑机制未变。
- 未验证/待办：全队列完成（长任务持续跑）；641 份历史完成件与后续新完成件的 ingest 需授权维护窗口；GLM 端并发上限确切值未知（按 1×2 实测稳定推进）。

## 观察入口

`tail -f ~/Library/Application\ Support/QuantMind/maintenance/pdf-text-driver/ocr.log`（看 document=N/stage= 标记与 quota 警告）；`pgrep -f "pdf-text-driver/driver.sh"`。
