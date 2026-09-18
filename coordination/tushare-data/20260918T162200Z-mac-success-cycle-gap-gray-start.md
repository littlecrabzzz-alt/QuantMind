# Mac Tushare 成功周期空档灰度提速开始

- 当前生产每轮约 769–778 次请求、101–103 秒，账户闸门为 500 次/分钟；worker 即使本轮成功且已超过 105 秒周期目标，仍固定休眠 5 秒，造成约 3%–4% 可避免空档。
- 候选仅把成功的真实采集周期最短空档降为 1 秒；`planning_only` 保持 5 秒，失败、blocked、disabled、already_running 等非成功状态保持至少 5 秒/原周期退避，供应商账户/API/每日限额不变。
- 分支 `codex/tushare-success-cycle-gap-20260919`，独立 worktree 开发；上线后用连续真实周期的 RPM、HTTP 状态和 rate-limit 证据灰度验收。
