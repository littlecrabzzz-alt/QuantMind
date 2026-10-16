# 主题：R01-P0.3 输入上界最小接口 + matcher 小额成交修复（p03_execution M6E1）

- 时间、节点、任务标识：2026-09-26 · mac · R01P0-M6E1（wave M6 attempt 1）
- 状态：**done**（不部署、不开 H2）
- **新 HEAD（冻结）**：`411c7e0b8ba48c03acfbaa874b8736de9bd77c6c`（仅 owns 4 文件；此后零提交）
- 证据：`artifacts/p03/sublot-fix/m6/`（README 代码行+跨界测试对照+回归/对账日志首行 HEAD）；附录 rev5

## 两项

1. read_through：daily/factors 类型转换前裁定、现金分红 record≤bound 保权（ex/pay 跨界应收连续）、share 只到授权生效日、非 PIT 假设显式声明、actual_max_input_date 输出、上界冻结 config→checkpoint 防未授权放大、同包双视图隔离；跨界五项合成测试（真实 v2 包 511090 2024-04）全过。
2. matcher fill<100 移除：BELOW_LOT_SIZE 只对申报量；量约束 fill 精确（200/37→37 余 163、100/1→1 余 99），买卖共享守卫；fill=0 仍拒。

回归 392 passed（+15）；v2 十窗口 ALL_PASS。
