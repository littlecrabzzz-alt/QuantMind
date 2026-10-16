# 主题：R01-P0.3 零股申报缺口裁决与修复（p03_execution M2E1，回 R01SELF）

- 时间、节点、任务标识：2026-09-26 · mac · R01P0-M2E1（wave M2 attempt 1）
- 结论：**接收并已修复**（received-fixed）
- 提交：`herdr/r01-p0` @ `1355232999cc71e533b9f5781f22861f4ea6264b`（仅 owns 2 文件）
- 证据：`<run>/artifacts/p03/sublot-fix/`（rerun-probe-head.json 复现、README 裁决+前后对照+官方依据+代码行）；合同附录 `artifacts/p01c/contracts/ledger-contract-v3.1-sublot-appendix.md`

## 裁决

本 worktree HEAD（605f76fc）只读复现成功：总仓=可卖=5、目标 2 → 申报 3、成交 3、留 2。
官方 §3.3.8（2026-07-06 生效、非暂缓）：零股余额须一次性全额申报——**判定缺陷成立**。
对方不外推边界全部采纳；禁用方案（规范化/改报/推定清仓/整手化合法部分成交）均未采用。

## 修复（申报时拒绝）

_rebalance 卖出申报处：合法 ⇔ 整手倍数 ∨ 覆盖全部余额 ∨ 零股尾额完整消费（余整手）；
否则拒单 sublot_partial_sell_not_allowed（含 total/available/declared/target_weight），
持仓/现金/目标不动。生效日 config `sublot_rule_effective`（默认 2026-07-06），此前维持
现行为（早期规则原文未取得，不作追溯声明）。105 三态/5→3/5→5/T+1/量约束部分成交/
生效边界共 7 用例；全量回归 336 passed；v2 十窗口 ALL_PASS。输入身份/包不变；A/B 冻结
口径不变（v3.1 附录）。

## 回信要点（主控转 R01SELF）

接收；修复分支 herdr/r01-p0@13552329（H2 线 tip，同时覆盖未来 H1 版本身份）；
ledger 合同以 v3.1 附录增补；部署窗口与 sidecar 切换由主控统一安排（本任务未部署）。

## 追加（2026-09-26：R01SELF 跨组 FYI 边界复核）

- 对方关切"105 先卖 100 留 5 被拒"**不成立**：本实现为三判据规则（整手∨全额∨尾额完整），105→100 判 lot_multiple 合法（测试显式断言）；"剩余>0且<100即拒"的表述从未被采用。
- 合法部分成交不整手化：撮合层卖出 fill=quantity（实测 卖5量3→成交3余2）。
- 1000→5 / 105→2 被判拒属 lot-multiple 要求的自然覆盖：无对方同级官方证据，已在合同附录/证据标注证据等级，如后续取证推翻按 change-control 收窄（config effective_date 可调）。
- 对方 checkpoint 精度 probe（100.443373→100.4434）：本 H2 线已由 J2E2（e83c40aa）修复；probe 基于 H1 c3746c3a 早于修复；H1 线是否并入由主控裁定，本组不扩任务。对方 probe/raw/coordination 未改动。
- 逐例判据复核 12 例全过（见 artifacts/p03/sublot-fix/README.md 追加段）；无代码变更，回归维持 336 passed。

## 追加（2026-09-26：M3E1 裁决验证+收窄，提交 078f67a8）

- 项 1：对方 checkpoint-gap 缺陷**裁决成立**（c3746c3a 确有 4dp/6dp 残留）；tip 复跑+补齐——J2E2 已修 positions，M3E1 补 HWM/风险事件/权益金额全精度；恢复逐位相等（qty 100.443373、HWM 30000.123456789 精确），重启==连续；精度语义入合同 v3.1 附录 rev2。
- 项 2：零股校验收窄至证据范围——唯一强制"可卖<100 且 0<申报<可卖"拒单；lot-multiple 扩展移除（105/1000 各例现行为放行，现状断言）；5→3 拒/5→5/部分成交不整手化/T+1/生效边界保留。回归 337 passed、v2 ALL_PASS。证据 artifacts/p03/sublot-fix/followup/。

## 追加（2026-09-26：M3E2 精度补齐，提交 06498162）

- M3R 第 1/3 项：确认净值 nav_at_confirm 取 nav_exact 全精度并全精度存储（原 4dp）；entitlement_qty/basis_multiplier 全精度导出；风险事件 nav/threshold 复核确认已全精度。最终提交重跑两 probe（followup/tip-rerun-both.*，head=06498162，旧文件 .prev）；回归 337 passed、v2 不回归。无范围扩展。
