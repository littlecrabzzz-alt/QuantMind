# Tushare fund_nav 历史精确批次候选就绪

- 时间、节点、任务标识：2026-09-10T11:54:59Z，Mac，`fund_nav_batch`。
- 状态：待交接；分支 `codex/tushare-fund-nav-batch`，基线 `ca9fdaf3d655ab973dd921e5a90634fde68e42b0`，独立 worktree。
- 分工：只读审计 `fund_nav`，新增专项准备器、执行器、测试、文档和固定候选；无 Token、上游、生产写入、发布或 `CURRENT` 切换。

真实 authority 有 52,570 个 `fund_nav` 任务；history 为 done 49、pending 22,207、split_pending 51。权限已由 103 次非空成功回执验证为 available。现有 51 个拆分根有 102 个 pending 子任务。本候选先固定这 102 个拆分叶，再取 258 个历史根，共 360 任务、309 基金；manifest SHA256 `ce4f8bbfca7be9e8ea9a7ab028b77286acec7eb61586ad9da70dff3b961fcbc8`，任务集合 SHA256 `7fc790ecc6f8975f5820c974dd8a9d7ae4e0d5d1c4b1e6a54c9ecb074a26c1be`，准备器 SHA256 `a4a4320a361cb710fb8fe6d91b0d4f6075d1a01e8c3dd8df2adbebccc27ba26e`，执行器 SHA256 `5fa32b52871722d8ab6c74e999f442d201a4cbef2b7f081228697148c7f7fe89`。离线 plan-only 为 0 authority、0 凭据、0 上游、0 发布。

基金全集仍有 13 个 `fund_basic` 代码未规划 `fund_nav`，另有 2 个已规划代码不在当前基础合并集；生命周期字段不完整，修订首次可知时间也未证明。候选显式保留这些边界，不按状态/日期裁剪历史窗口。预计生产首批 43.2–90 秒、约 67 MiB，按观测最大响应和元数据预留 200 MiB；审计时空闲 153,100,898,304 字节。

验证：专项 unittest 4 项通过；候选 plan-only 校验通过；`py_compile` 和 `git diff --check` 通过。接手者合入后先确认候选任务仍为 pending、配置和工具哈希不变，再自然排空相关 worker并使用 exact runner；执行器失败关闭且不发布。详见 `docs/tushare-fund-nav-batch.md`。
