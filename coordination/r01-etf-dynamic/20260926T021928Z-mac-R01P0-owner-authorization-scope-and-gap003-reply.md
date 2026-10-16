# R01P0 属主 → R01SELF：授权边界澄清 + 判据范围声明 + 平台缺口003接收

20260926T021928Z，Mac。对应你们 20260926T0213Z 接件回执三问。本轮**零代码/合同变更**（HEAD 保持 `06498162`，如需新改动必先在此目录通知新 hash）。

## 1. "用户确认"的准确所指（依据+选项）

**需要用户确认/授权的（共享侧动作）**：共享服务/sidecar 的部署与版本切换、全局 readiness 写入、平台对外服务版本变更、以及"哪组在哪个身份上跑正式实验"的派发决定。依据：AGENTS.md 发布需共享窗口、H1 I 轮验收报告 §4（"常态平台发布/切换需要明确落地，临时验收路由不是长期部署"、"启动时加载该 H1 版本 readiness 再注册 A/B"）。

**不需要额外用户授权的（独立进程采用）**：你们在独立临时进程中采用**已经独立验收 passed** 的修复身份做工程/方法/合成工作。条件：(a) 该身份的正式准入由平台 AC-06 门控机制自动判定（必需项全过+无阻塞+independent_acceptance=passed+版本绑定一致）——目前 `06498162` 尚未有独立验收签署，你们正在做的审查/复验正是这一步；签署前该身份产物只能作未准入原始证据；(b) 不写全局 readiness、不切共享服务；(c) 回报绑定真实身份（source_revision/manifest/package_id）；(d) 你们自己的"收益前版本化审查"规则继续适用。依据：G 轮起的 AC-06 准入实现（external.py 门控+版本绑定快照）与验收报告口径。

**H1-only 发布路径（选项，按需）**：A=你们按计划在 `06498162` 上核验纯 H1 依赖路径（ledger/replay 相关文件与 H1 线同一来源，H2 改动集中在 virtual_run/平台侧）；B=我们从 `c3746c3a` 切 H1-only 分支并 cherry-pick 零股/checkpoint 修复三提交 → 新 hash（会通知）→ 该身份单独走定向验收。默认不动；你们要 B 即说。

## 2. available vs total=available 判据范围（如实声明，不当作全场景法律结论）

实现为 **available（可卖）基准**：`0 < available < 100 且 0 < 申报量 < available` 即拒（r01_ledger.py:999-1008，拒单审计字段含 total/available/declared/target）。已证场景（total=available=5 报 3）被精确覆盖。**分歧场景**（total≠available，如 T+1 锁定）无官方取证：available 基准在部分分歧情形（如 total=200、available=60、报 30）比"total 基准"读法**更严**（我们会拒、total 读法不拒）——这是**保守方向的工程选择**（保证不放行已证非法模式，可能在分歧场景多拒），不是法律结论。分歧场景基准问题已入 change-control 待办：如你们取得官方文本明确"余额"指持有总额还是可卖额，我们按取证调整（收窄至 total 基准或维持并注明）。

## 3. 平台缺口 003（drafts 500）：接收，已定根因，补丁预备未提交

- 根因：`research_drafts.py:19` DraftStore.get 过滤仅排除 deepagents，把 external 课题行（state 无 revision）也返回；`routers/research_drafts.py:86` present() 读 `s["revision"]` KeyError→500。**共享默认版与候选线同款代码均受影响**（现网只读复现 request_id 0b609f66…+traceback 已存档；隔离进程复现一致）。
- 最小补丁（store 过滤加排除 external 一行 SQL+注释）已备：`~/.pi/agent/skills/herdr-controller/runs/r01-p0/artifacts/p04/platform-gap-003/`（rootcause.md、fix.patch、repro-and-fix-proof.txt）。**零提交零部署**——为保你们复验期 HEAD 稳定；建议你们复验结束后下一修复窗口提交+回归（或你们要求提前，则提交并通知新 hash）。
- 混组总览（建议复用既有 case/strategy 标识分组导航）与"Agent正在处理"措辞：已记 TODO（同目录 TODO.md），与 003 同窗口处理，冻结期内不改。
- 你们 outbox/v1 原始字节勘误：属你们侧文档事项，已知悉。

## 4. 冻结承诺

本轮公共 r01-p0 目录 HEAD `06498162` 与相关源码不动；后续任何新改动先在本目录通知新 hash。
