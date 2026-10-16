# 主题：R01-P0.3 份额折算精度修复（p03_execution J2E2）

- 时间、节点、任务标识：2026-09-25 · mac · R01P0-J2E2（wave J2-fix attempt 2）
- 状态：**done**
- 提交：`herdr/r01-p0` @ `e83c40aa7a0eec0b7aa5088b4e1338aae4ce3e65`（仅 owns 1 文件）
- 证据：`<run>/artifacts/p03/h2/fixes-j2/README.md`（前后对照+精度政策）；view-fields-v2.md 追加精度政策段

## 要点

根因：checkpoint 往返经 LedgerPosition.to_dict 把 qty 舍到 4dp（100.443373→100.4434），复算侧全精度 → d20260918 折算日重启 vs 连续 nav 差 −0.0038。修复：**内部/检查点/审计原件全精度，仅展示层（export_view）格式化**（qty/last_mark/市值 4dp、成本 6dp；view_schema 仍 2）。修复后重启 vs 连续 nav 差=0.0（精确）、复算=0.0 不回归；全量回归 316 passed、v2 十窗口 ALL_PASS、33/33 分红对账。
