# OCR 两缺陷修复（第5线复核轮）

- 节点、任务：Mac，ocr-driver-cycle-fix-4e71；接续 [ocr-quota-recovery-9d2f](20261016T182647Z-mac-ocr-quota-recovery-9d2f.md)。父复核发现两真实缺陷，本轮修复并复验。

## 缺陷与修复

1. driver.sh（zsh）`status=$(...)` 赋值撞 zsh 只读特殊变量 `status`，首个 cycle 结束即 "read-only variable" 退出。修复：改普通变量 `last_line`；driver 收录 repo `scripts/pdf_text_driver.sh`（维护副本同内容部署），新增 `QM_OCR_*` fixture 覆盖钩子（M/RT/ROOT/ST/STAGE/BACKOFF/PAUSE/PARSE_PATTERN，生产默认不变）。
2. `page_workers>1` 用 `pool.map`：配额异常上抛后 `with.__exit__` 仅 `shutdown(wait=True)`，会继续执行全部已排队页（大文档每页最高 1800s 预算 → cycle 可能排队数天）。修复：显式 submit + 顺序 `future.result()`；首个异常 `stop.set()` + `future.cancel()` 未开始页，配额循环每轮顶部检查 stop（含 sleep 醒来后）及时退出；已完成 checkpoint 与渲染临时目录语义不变。

## 验证

- 回归 17 项全过（新增：`test_parallel_quota_stops_queue_instead_of_draining_it`——6页/2worker/恒配额，断言模型调用数≤34（无取消时≥78），证明不排空队列即上抛；`test_pdf_text_driver.py` 两项 fixture cycle 测试——quota 退避分支与未知状态暂停分支均干净退出 rc=0/stderr空，旧 driver 的只读变量错误在此测试下必然非零退出）；ruff 通过。
- 部署：worktree 提交 cb06e8e7（db7d1c7c 之上）；运行副本模块已同步，driver 部署至 maintenance/pdf-text-driver/driver.sh（缺陷版留档 driver.sh.bak-20261016-v1，更早原版见上轮记录转述）；进程重启 nohup（driver 2379）。
- 清理：按父要求移除新测试中 `fallback.assert_called_once`/`run.call_args` 纯 wiring 断言，保留真实解析/错误拒绝/断点行为断言。

## 观察/待办（同上轮）

ingest 仍需授权维护窗口；全队列长任务持续；真实 smoke 见本轮会话证据（document= 持续推进、完成 json 累计）。

## 追加（同轮第三次修复）

driver 的 `STAGE` 变量经 `eval` 展开时 `$ROOT/$ST` 未加引号，"Application Support" 空格分词导致 argparse 拒参、driver 进入 60s 错误循环（fixture 路径无空格故首测未拦截）。修复：默认 STAGE 内对两路径转义引号；新增带空格路径的默认命令回归（真实 venv + 空格 fixture root，断言无 "unrecognized arguments" 且出 no_candidates）；顺带修复编辑中丢失的 `PAUSE` 定义（该缺陷被 cycle 测试 stderr 断言当场捕获）。最终提交 af8bdf3c，18 项测试 3 次全过，部署副本与 worktree 逐字节一致（diff 空）。重启后真实推进：本 cycle 完成 5 文档/117 页（其中 3 文档 37+18+9 页为本轮真实转写），driver/stage 存活，日志无新的 usage 错误。
