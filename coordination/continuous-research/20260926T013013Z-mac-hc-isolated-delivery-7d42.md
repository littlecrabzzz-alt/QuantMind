# Herdr controller 隔离优化包交付（主机本地）

- 时间：2026-09-26T01:30Z；本主题维护者 7d42。
- 用户追加要求：减少新 worktree 开工重复检查/token，封装脚本并改善展示；不改正在工作的 session。
- 只读检查了 `r01-etf-dynamic-self` 与 `r01x-fixed-alloc` 的六个初始 session。确认相对路径误读、缺精确入口导致全仓搜索、读取其他任务和大段 stdout 等可避免开销；不把职责内独立数据/合同复核当成浪费。

## 已交付

- 新入口：`~/.local/bin/hc-v15`。固定包：`~/.local/share/herdr-controller/v15/packages/babc72aa837ea0581b65d982908927c44e9f078c/`。
- `prepare/context-check/prompt --prepared`：代码/文件身份收据、绝对路径、按职责分包、长度上限、派发前失效检查与 write_paths 自动登记。
- `board`：任务名优先；进程/传输/结果分列；默认只读。原生 pane/workspace display metadata 为显式 `--publish`，仅独立登记且 schema=2 的新资源，全批预检、30秒 TTL；本次未应用到活动资源。
- 已合入候选的前期安全改造：默认关闭保留 worktree、显式删除护栏、身份/生命周期锁、派发和结果闭环、内容 pin、freeze/verify、元数据监控与文档。

## 验证

- `ecbd41c0adf1b7a55933bd7a5a29d1c459730e02`：246 项完整 unittest，734.566s，全过。
- 最终 `babc72aa837ea0581b65d982908927c44e9f078c` 仅增加“按 schema 判断兼容，不按并行维护者升号”的看板修复和文档：28 项针对 prepare/board/真实 state+fake Herdr 整合回归全过；不把它们相加冒充独立用例总数。
- Ruff、bash -n、Markdown 本地链接检查通过；LSP 12 文件零诊断（最终改动另经 Ruff 与定向回归）。
- 安装包 29/29 文件哈希一致；安装入口在临时 Git 上完成 prepare→check→零写复用→材料漂移拒绝；没有真实 Herdr 创建/派发/删除 smoke。
- 安装版已对两个实际 run 做只读看板预览，退出0。独立 registry/runs 仍为空。
- 证据：`~/.local/share/herdr-controller-maintenance/20260925T153222Z-v15/{final-regression.log,final-targeted.log,board-preview.txt}`；安装清单 `~/.local/share/herdr-controller/v15/INSTALL.json`。

## 保留边界与接续

- 未更改任何既有 session/agent/pane、旧 run/registry；未给他们补消息、改名、重启、迁移或改显示元数据。活动 run 由其原控制者继续更新，不能声称它们哈希完全不变。
- 期间发现另一控制者把现用 SKILL/hc 从 v14 更新到 v16（仍旧账本格式）。已保留其修改；默认 `hc` 仍指向原入口。本包的 v15 是隔离维护线，不代表比 v16 数字更大或已合并主线。
- 新入口强制独立 `v15/state`、`v15/runs`、`v15/releases`。旧 run 仅可只读看，不复制 registry 或自动授予历史任务验收。默认切换/并行修改整合另占明确空闲窗口。
- 没有改 QuantMind 业务代码、云端服务/数据库、固定研究输入、模型配置或 Herdr server；未提交或推送 QuantMind 主仓其他修改。候选自己的 Git 仓库 clean。
- 准备器/显示不是 OS 沙箱、业务准入或自动节省比例证明。真实原生 UI 发布仅做 API 参数/替身测试，未对活动用户界面试写。
- 文档入口：包内 `references/low-overhead.md`、`templates/prepare.json`、`references/operations.md`。
- 回退仅停用独立 `hc-v15` 入口；不要把维护前 baseline 回灌默认 hc，以免覆盖另一控制者的 v16 修改。若后续已建立 v15 run，先保留其固定 runtime/账本，不删除历史来回退。
