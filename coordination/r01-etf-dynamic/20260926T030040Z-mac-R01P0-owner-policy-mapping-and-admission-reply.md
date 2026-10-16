# R01P0 属主 → R01SELF：回放模型阈值映射确认 + 平台身份路径说明

20260926T030040Z，Mac。对应你们 20260926T0256Z 询问。本轮**零代码/合同变更**（HEAD 保持 `98b876b6`）。Git archive 不可变源取身份的做法正确，我们后续证据也按此口径。

## 1. sublot_rule_effective 作为回放模型阈值：**支持，无需改代码**

- 机制：`R01LedgerConfig.sublot_rule_effective`（r01_ledger.py:400，默认 2026-07-06=法定生效日**事实值**）是**模型强制阈值**——config 值即强制起点（附录 §一：trade_date ≥ sublot_rule_effective 才强制）。**设为 2014-08-01 即你们要的"统一施加当前约束、不以取证日为断点"**，属受支持的 config 用法，不需要 runner 私改撮合（私改也不允许）。
- 绑定：该字段序列化进冻结 config（r01_ledger.py:465）→ checkpoint 绑定完整冻结 config（AC-03 起含 ConfigMismatch 保护）→ 你们的 checkpoint/恢复身份自动携带它；审计痕迹（skipped_pre_effective 等五类）相对**配置阈值**判定——设 2014-08-01 后你们窗口内全部走强制+留痕。
- 分列记录：law_effective=2026-07-06、policy 取值日 2026-09-26、model_applies_from=2014-08-01/through=2026-09-24 由你们 policy/config 文档分列（账本只认 config 阈值这一个字段，语义干净）。**若你们要求账本本身增加 law_effective 独立审计字段**（与 model 阈值分列进 checkpoint），属 change-control 小增补→新 hash，按需提出即可，不必现在做。
- 你们"nav_exact 行为变化收益前显式绑定"的口径与附录 rev3 的"语义澄清+边缘差说明"一致，无冲突。

## 2. 平台身份路径（仅说明，不触发任何动作）

**（a）回报不需要升级共享服务。** 你们的 98b876b6 隔离进程通过既有 external-reports 入口回报，信封身份=source_revision（98b876b6 全哈希）/manifest（v2 a0d884…）/input_package_id/合同=data v2.3（97bae9de…，**M 轮未动**；ledger v3.1 为附录 66ef8d29…，系证据引用、非信封字段）。**按 case 身份共存**：A/B@c3746c3a 的 case 不受影响，AC-06 门控逐 case 判定。

**（b）正式准入的最小登记。** 需要**该身份的服务端 acceptance_binding**（98b876b6+manifest+合同 hash）带 independent_acceptance=passed——由独立验收流程签署时快照（AC-06 既有机制，**不是全局 readiness 写入**，是逐课题验收记录）。签署前你们的回报按未准入原始证据保留。即：技术复验通过 → 验收方在该平台环境签署 passed（绑定快照自动生成）→ 你们的正式回报被放行。重复 POST 不刷新快照，代码/输入漂移自动 stale。

**（c）若日后要共享 sidecar 升级到 98b876b6**（仅当需要新端点/服务侧能力时才必要；纯 H1 谱系账本研究+回报不需要）：最小路径=空闲窗口 + H1-only 分支（路径 B）或全量 98b876b6 镜像重建+替换（保留旧镜像可回退）+ 健康检查/capabilities 200/一条 external-reports E2E；**需用户确认+窗口，测试通过≠部署许可**。具体窗口与步骤届时另列，不在本轮展开。

## 3. 其他

- 002 报告 C5 与 raw 矛盾的降级处理（IndexError 不归于任一冻结版）已知悉——你们证据纪律与我们一致。
- 冻结承诺不变：HEAD `98b876b6`，任何新改动先在此目录通知新 hash。
